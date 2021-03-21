# -*- coding: utf-8 -*-
from __future__ import unicode_literals, print_function

import binascii
import codecs
import os
import platform
import re
import subprocess
import threading
import time

import frida


def main():
    from colorama import Fore, Style
    import json

    from frida_tools.application import ConsoleApplication, input_with_cancellable

    class TracerApplication(ConsoleApplication, UI):
        def __init__(self):
            super(TracerApplication, self).__init__(self._await_ctrl_c)
            self._palette = [Fore.CYAN, Fore.MAGENTA, Fore.YELLOW, Fore.GREEN, Fore.RED, Fore.BLUE]
            self._next_color = 0
            self._attributes_by_thread_id = {}
            self._last_event_tid = -1

        def _add_options(self, parser):
            pb = TracerProfileBuilder()
            def process_builder_arg(option, opt_str, value, parser, method, **kwargs):
                method(value)
            parser.add_option("-I", "--include-module", help="include MODULE", metavar="MODULE",
                    type='string', action='callback', callback=process_builder_arg, callback_args=(pb.include_modules,))
            parser.add_option("-X", "--exclude-module", help="exclude MODULE", metavar="MODULE",
                    type='string', action='callback', callback=process_builder_arg, callback_args=(pb.exclude_modules,))
            parser.add_option("-i", "--include", help="include FUNCTION", metavar="FUNCTION",
                    type='string', action='callback', callback=process_builder_arg, callback_args=(pb.include,))
            parser.add_option("-x", "--exclude", help="exclude FUNCTION", metavar="FUNCTION",
                    type='string', action='callback', callback=process_builder_arg, callback_args=(pb.exclude,))
            parser.add_option("-a", "--add", help="add MODULE!OFFSET", metavar="MODULE!OFFSET",
                    type='string', action='callback', callback=process_builder_arg, callback_args=(pb.include_relative_address,))
            parser.add_option("-z", "--addmany", help="add a MODULE!OFFSET!NAME related file path",
                              metavar="MODULE!OFFSET!NAME",
                              type='string', action='callback',
                              callback=process_builder_arg,
                              callback_args=(pb.include_relative_address_path,))
            parser.add_option("-T", "--include-imports", help="include program's imports",
                    action='callback', callback=process_builder_arg, callback_args=(pb.include_imports,))
            parser.add_option("-t", "--include-module-imports", help="include MODULE imports", metavar="MODULE",
                    type='string', action='callback', callback=process_builder_arg, callback_args=(pb.include_imports,))
            parser.add_option("-m", "--include-objc-method", help="include OBJC_METHOD", metavar="OBJC_METHOD",
                    type='string', action='callback', callback=process_builder_arg, callback_args=(pb.include_objc_method,))
            parser.add_option("-M", "--exclude-objc-method", help="exclude OBJC_METHOD", metavar="OBJC_METHOD",
                    type='string', action='callback', callback=process_builder_arg, callback_args=(pb.exclude_objc_method,))
            parser.add_option("-j", "--include-java-method", help="include JAVA_METHOD", metavar="JAVA_METHOD",
                    type='string', action='callback', callback=process_builder_arg, callback_args=(pb.include_java_method,))
            parser.add_option("-J", "--exclude-java-method", help="exclude JAVA_METHOD", metavar="JAVA_METHOD",
                    type='string', action='callback', callback=process_builder_arg, callback_args=(pb.exclude_java_method,))
            parser.add_option("-s", "--include-debug-symbol", help="include DEBUG_SYMBOL", metavar="DEBUG_SYMBOL",
                    type='string', action='callback', callback=process_builder_arg, callback_args=(pb.include_debug_symbol,))
            parser.add_option("-q", "--quiet", help="do not format output messages", action='store_true', default=False)
            parser.add_option("-d", "--decorate", help="add module name to generated onEnter log statement", action='store_true', default=False)
            parser.add_option("-S", "--init-session", help="path to JavaScript file used to initialize the session", metavar="PATH",
                    type='string', action='append', default=[])
            parser.add_option("-P", "--parameters", help="parameters as JSON, exposed as a global named 'parameters'", metavar="PARAMETERS_JSON",
                    type='string', action='store', default=None)
            parser.add_option("-o", "--output", help="dump messages to file", metavar="OUTPUT", type='string')
            self._profile_builder = pb

        def _usage(self):
            return "usage: %prog [options] target"

        def _initialize(self, parser, options, args):
            self._tracer = None
            self._profile = self._profile_builder.build()
            self._quiet = options.quiet
            self._decorate = options.decorate
            self._output = None
            self._output_path = options.output

            self._init_scripts = []
            for path in options.init_session:
                with codecs.open(path, 'rb', 'utf-8') as f:
                    source = f.read()
                self._init_scripts.append(InitScript(path, source))

            if options.parameters is not None:
                try:
                    params = json.loads(options.parameters)
                except Exception as e:
                    raise ValueError("failed to parse parameters argument as JSON: {}".format(e))
                if not isinstance(params, dict):
                    raise ValueError("failed to parse parameters argument as JSON: not an object")
                self._parameters = params
            else:
                self._parameters = {}

        def _needs_target(self):
            return True

        def _start(self):
            if self._output_path is not None:
                self._output = OutputFile(self._output_path)

            stage = 'early' if self._target[0] == 'file' else 'late'

            self._tracer = Tracer(self._reactor, FileRepository(self._reactor, self._decorate), self._profile,
                    self._init_scripts, log_handler=self._log)
            try:
                self._tracer.start_trace(self._session, stage, self._parameters, self._runtime, self)
            except Exception as e:
                self._update_status("Failed to start tracing: {error}".format(error=e))
                self._exit(1)

        def _stop(self):
            self._tracer.stop()
            self._tracer = None
            if self._output is not None:
                self._output.close()
            self._output = None

        def _await_ctrl_c(self, reactor):
            while True:
                try:
                    input_with_cancellable(reactor.ui_cancellable)
                except frida.OperationCancelledError:
                    break
                except KeyboardInterrupt:
                    break

        def on_trace_progress(self, status, *params):
            if status == 'initializing':
                self._update_status("Instrumenting...")
            elif status == 'initialized':
                self._resume()
            elif status == 'started':
                (count,) = params
                if count == 1:
                    plural = ""
                else:
                    plural = "s"
                self._update_status("Started tracing %d function%s. Press Ctrl+C to stop." % (count, plural))

        def on_trace_warning(self, message):
            self._print(Fore.RED + Style.BRIGHT + "Warning" + Style.RESET_ALL + ": " + message)

        def on_trace_error(self, message):
            self._print(Fore.RED + Style.BRIGHT + "Error" + Style.RESET_ALL + ": " + message)
            self._exit(1)

        def on_trace_events(self, events):
            no_attributes = Style.RESET_ALL
            for timestamp, thread_id, depth, message in events:
                if self._output is not None:
                    self._output.append(message + "\n")
                elif self._quiet:
                    self._print(message)
                else:
                    indent = depth * "   | "
                    attributes = self._get_attributes(thread_id)
                    if thread_id != self._last_event_tid:
                        self._print("%s           /* TID 0x%x */%s" % (attributes, thread_id, Style.RESET_ALL))
                        self._last_event_tid = thread_id
                    self._print("%6d ms  %s%s%s%s" % (timestamp, attributes, indent, message, no_attributes))

        def on_trace_handler_create(self, target, handler, source):
            if self._quiet:
                return
            self._print("%s: Auto-generated handler at \"%s\"" % (target, source.replace("\\", "\\\\")))

        def on_trace_handler_load(self, target, handler, source):
            if self._quiet:
                return
            self._print("%s: Loaded handler at \"%s\"" % (target, source.replace("\\", "\\\\")))

        def _get_attributes(self, thread_id):
            attributes = self._attributes_by_thread_id.get(thread_id, None)
            if attributes is None:
                color = self._next_color
                self._next_color += 1
                attributes = self._palette[color % len(self._palette)]
                if (1 + int(color / len(self._palette))) % 2 == 0:
                    attributes += Style.BRIGHT
                self._attributes_by_thread_id[thread_id] = attributes
            return attributes

    app = TracerApplication()
    app.run()


class TracerProfileBuilder(object):
    def __init__(self):
        self._spec = []

    def include_modules(self, *module_name_globs):
        for m in module_name_globs:
            self._spec.append(('include', 'module', m))
        return self

    def exclude_modules(self, *module_name_globs):
        for m in module_name_globs:
            self._spec.append(('exclude', 'module', m))
        return self

    def include(self, *function_name_globs):
        for f in function_name_globs:
            self._spec.append(('include', 'function', f))
        return self

    def exclude(self, *function_name_globs):
        for f in function_name_globs:
            self._spec.append(('exclude', 'function', f))
        return self

    def include_relative_address(self, *address_rel_offsets):
        for f in address_rel_offsets:
            self._spec.append(('include', 'relative-function', f))
        return self


    def include_relative_address_path(self, *address_rel_offsets_path):
        with open(address_rel_offsets_path[0],"r",encoding="utf-8")as F:
            address_rel_offsets = F.readlines()

        for address_rel in address_rel_offsets:
            address_rel = address_rel.replace("\n","")
            self._spec.append(('include', 'relative-function-many', address_rel))
        return self

    def include_imports(self, *module_name_globs):
        for m in module_name_globs:
            self._spec.append(('include', 'imports', m))
        return self

    def include_objc_method(self, *function_name_globs):
        for f in function_name_globs:
            self._spec.append(('include', 'objc-method', f))
        return self

    def exclude_objc_method(self, *function_name_globs):
        for f in function_name_globs:
            self._spec.append(('exclude', 'objc-method', f))
        return self

    def include_java_method(self, *function_name_globs):
        for f in function_name_globs:
            self._spec.append(('include', 'java-method', f))
        return self

    def exclude_java_method(self, *function_name_globs):
        for f in function_name_globs:
            self._spec.append(('exclude', 'java-method', f))
        return self

    def include_debug_symbol(self, *function_name_globs):
        for f in function_name_globs:
            self._spec.append(('include', 'debug-symbol', f))
        return self

    def build(self):
        return TracerProfile(self._spec)


class TracerProfile(object):
    def __init__(self, spec):
        self.spec = spec


class Tracer(object):
    def __init__(self, reactor, repository, profile, init_scripts=[], log_handler=None):
        self._reactor = reactor
        self._repository = repository
        self._profile = profile
        self._script = None
        self._agent = None
        self._init_scripts = init_scripts
        self._log_handler = log_handler

    def start_trace(self, session, stage, parameters, runtime, ui):
        def on_create(*args):
            ui.on_trace_handler_create(*args)
        self._repository.on_create(on_create)

        def on_load(*args):
            ui.on_trace_handler_load(*args)
        self._repository.on_load(on_load)

        def on_update(target, handler, source):
            self._agent.update(target.identifier, target.display_name, handler)
        self._repository.on_update(on_update)

        def on_message(message, data):
            self._reactor.schedule(lambda: self._on_message(message, data, ui))

        ui.on_trace_progress('initializing')
        data_dir = os.path.dirname(__file__)
        with codecs.open(os.path.join(data_dir, "tracer_agent.js"), 'r', 'utf-8') as f:
            source = f.read()
        runtime = 'v8' if runtime == 'v8' else 'qjs'
        script = session.create_script(name="tracer",
                                       source=source,
                                       runtime=runtime)

        self._script = script
        script.set_log_handler(self._log_handler)
        script.on('message', on_message)
        script.load()

        self._agent = script.exports

        raw_init_scripts = [{ 'filename': script.filename, 'source': script.source } for script in self._init_scripts]
        self._agent.init(stage, parameters, raw_init_scripts, self._profile.spec)

    def stop(self):
        if self._script is not None:
            try:
                self._script.unload()
            except:
                pass
            self._script = None

    def _on_message(self, message, data, ui):
        handled = False

        if message['type'] == 'send':
            try:
                payload = message['payload']
                mtype = payload['type']
                params = (mtype, payload, data, ui)
            except:
                # As user scripts may use send() we need to be prepared for this.
                params = None
            if params is not None:
                handled = self._try_handle_message(*params)

        if not handled:
            print(message)

    def _try_handle_message(self, mtype, params, data, ui):
        if mtype == "events:add":
            events = [(timestamp, thread_id, depth, message) for target_id, timestamp, thread_id, depth, message in params['events']]
            ui.on_trace_events(events)
            return True

        if mtype == "handlers:get":
            flavor = params['flavor']
            base_id = params['baseId']

            scripts = []
            response = {
                'type': "reply:{}".format(base_id),
                'scripts': scripts
            }

            repo = self._repository
            next_id = base_id
            for scope in params['scopes']:
                scope_name = scope['name']
                for member_name in scope['members']:
                    target = TraceTarget(next_id, flavor, scope_name, member_name)
                    next_id += 1
                    handler = repo.ensure_handler(target)
                    scripts.append(handler)

            self._script.post(response)

            return True

        if mtype == "agent:initialized":
            ui.on_trace_progress('initialized')
            return True

        if mtype == "agent:started":
            self._repository.commit_handlers()
            ui.on_trace_progress('started', params['count'])
            return True

        if mtype == "agent:warning":
            ui.on_trace_warning(params['message'])
            return True

        if mtype == "agent:error":
            ui.on_trace_error(params['message'])
            return True

        return False


class TraceTarget(object):
    def __init__(self, identifier, flavor, scope, name):
        self.identifier = identifier
        self.flavor = flavor
        self.scope = scope
        if isinstance(name, list):
            self.name = name[0]
            self.display_name = name[1]
        else:
            self.name = name
            self.display_name = name

    def __str__(self):
        return self.display_name


class Repository(object):
    def __init__(self):
        self._on_create_callback = None
        self._on_load_callback = None
        self._on_update_callback = None
        self._decorate = False

    def ensure_handler(self, target):
        raise NotImplementedError("not implemented")

    def commit_handlers(self):
        pass

    def on_create(self, callback):
        self._on_create_callback = callback

    def on_load(self, callback):
        self._on_load_callback = callback

    def on_update(self, callback):
        self._on_update_callback = callback

    def _notify_create(self, target, handler, source):
        if self._on_create_callback is not None:
            self._on_create_callback(target, handler, source)

    def _notify_load(self, target, handler, source):
        if self._on_load_callback is not None:
            self._on_load_callback(target, handler, source)

    def _notify_update(self, target, handler, source):
        if self._on_update_callback is not None:
            self._on_update_callback(target, handler, source)

    def _create_stub_handler(self, target, decorate):
        if target.flavor == 'java':
            return self._create_stub_java_handler(target, decorate)
        else:
            return self._create_stub_native_handler(target, decorate)

    def _create_stub_native_handler(self, target, decorate):
        if target.flavor == 'objc':
            state = {"index": 2}
            def objc_arg(m):
                index = state["index"]
                r = ":${args[%d]} " % index
                state["index"] = index + 1
                return r

            log_str = "`" + re.sub(r':', objc_arg, target.display_name) + "`"
            if log_str.endswith("} ]`"):
                log_str = log_str[:-3] + "]`"
        else:
            for man_section in (2, 3):
                args = []
                try:
                    with open(os.devnull, 'w') as devnull:
                        man_argv = ["man"]
                        if platform.system() != "Darwin":
                            man_argv.extend(["-E", "UTF-8"])
                        man_argv.extend(["-P", "col -b", str(man_section), target.name])
                        output = subprocess.check_output(man_argv, stderr=devnull)
                    match = re.search(r"^SYNOPSIS(?:.|\n)*?((?:^.+$\n)* {5}\w+[ \*\n]*" + target.name + r"\((?:.+\,\s*?$\n)*?(?:.+\;$\n))(?:.|\n)*^DESCRIPTION", output.decode('UTF-8', errors='replace'), re.MULTILINE)
                    if match:
                        decl = match.group(1)

                        for argm in re.finditer(r"[\(,]\s*(.+?)\s*\b(\w+)(?=[,\)])", decl):
                            typ = argm.group(1)
                            arg = argm.group(2)
                            if arg == "void":
                                continue
                            if arg == "...":
                                args.append("\", ...\" +");
                                continue

                            read_ops = ""
                            annotate_pre = ""
                            annotate_post = ""

                            normalized_type = re.sub(r"\s+", "", typ)
                            if normalized_type.endswith("*restrict"):
                                normalized_type = normalized_type[:-8]
                            if normalized_type in ("char*", "constchar*"):
                                read_ops = ".readUtf8String()"
                                annotate_pre = "\""
                                annotate_post = "\""

                            arg_index = len(args)

                            args.append("%(arg_name)s=%(annotate_pre)s${args[%(arg_index)s]%(read_ops)s}%(annotate_post)s" % {
                                "arg_name": arg,
                                "arg_index": arg_index,
                                "read_ops": read_ops,
                                "annotate_pre": annotate_pre,
                                "annotate_post": annotate_post
                            })
                        break
                except Exception as e:
                    pass

            if decorate:
                module_string = " [%s]" % os.path.basename(target.scope)
            else:
                module_string = ""

            if len(args) == 0:
                log_str = "'%(name)s()%(module_string)s'" % { "name": target.name, "module_string" : module_string }
            else:
                log_str = "`%(name)s(%(args)s)%(module_string)s`" % {
                    "name": target.name,
                    "args": ", ".join(args),
                    "module_string": module_string
                }

        return """\
/*
 * Auto-generated by Frida. Please modify to match the signature of %(display_name)s.
 * This stub is currently auto-generated from manpages when available.
 *
 * For full API reference, see: https://frida.re/docs/javascript-api/
 */

{
  /**
   * Called synchronously when about to call %(display_name)s.
   *
   * @this {object} - Object allowing you to store state for use in onLeave.
   * @param {function} log - Call this function with a string to be presented to the user.
   * @param {array} args - Function arguments represented as an array of NativePointer objects.
   * For example use args[0].readUtf8String() if the first argument is a pointer to a C string encoded as UTF-8.
   * It is also possible to modify arguments by assigning a NativePointer object to an element of this array.
   * @param {object} state - Object allowing you to keep state across function calls.
   * Only one JavaScript function will execute at a time, so do not worry about race-conditions.
   * However, do not use this to store function arguments across onEnter/onLeave, but instead
   * use "this" which is an object for keeping state local to an invocation.
   */
  onEnter(log, args, state) {
    log(%(log_str)s);
  },

  /**
   * Called synchronously when about to return from %(display_name)s.
   *
   * See onEnter for details.
   *
   * @this {object} - Object allowing you to access state stored in onEnter.
   * @param {function} log - Call this function with a string to be presented to the user.
   * @param {NativePointer} retval - Return value represented as a NativePointer object.
   * @param {object} state - Object allowing you to keep state across function calls.
   */
  onLeave(log, retval, state) {
  }
}
""" % {"display_name": target.display_name, "log_str": log_str}

    def _create_stub_java_handler(self, target, decorate):
        return """\
/*
 * Auto-generated by Frida. Please modify to match the signature of %(display_name)s.
 *
 * For full API reference, see: https://frida.re/docs/javascript-api/
 */

{
  /**
   * Called synchronously when about to call %(display_name)s.
   *
   * @this {object} - The Java class or instance.
   * @param {function} log - Call this function with a string to be presented to the user.
   * @param {array} args - Java method arguments.
   * @param {object} state - Object allowing you to keep state across function calls.
   */
  onEnter(log, args, state) {
    log(`%(display_name)s(${args.map(JSON.stringify).join(', ')})`);
  },

  /**
   * Called synchronously when about to return from %(display_name)s.
   *
   * See onEnter for details.
   *
   * @this {object} - The Java class or instance.
   * @param {function} log - Call this function with a string to be presented to the user.
   * @param {NativePointer} retval - Return value.
   * @param {object} state - Object allowing you to keep state across function calls.
   */
  onLeave(log, retval, state) {
    if (retval !== undefined) {
      log(`<= ${JSON.stringify(retval)}`);
    }
  }
}
""" % {"display_name": target.display_name}


class MemoryRepository(Repository):
    def __init__(self):
        super(MemoryRepository, self).__init__()
        self._handlers = {}

    def ensure_handler(self, target):
        handler = self._handlers.get(target)
        if handler is None:
            handler = self._create_stub_handler(target, False)
            self._handlers[target] = handler
            self._notify_create(target, handler, "memory")
        else:
            self._notify_load(target, handler, "memory")
        return handler


class FileRepository(Repository):
    def __init__(self, reactor, decorate):
        super(FileRepository, self).__init__()
        self._reactor = reactor
        self._handler_by_id = {}
        self._handler_by_file = {}
        self._changed_files = set()
        self._last_change_id = 0
        self._repo_dir = os.path.join(os.getcwd(), "__handlers__")
        self._repo_monitors = {}
        self._decorate = decorate

    def ensure_handler(self, target):
        entry = self._handler_by_id.get(target.identifier)
        if entry is not None:
            (target, handler, handler_file) = entry
            return handler

        handler = None

        scope = target.scope
        if len(scope) > 0:
            handler_file = os.path.join(self._repo_dir, to_filename(os.path.basename(scope)), to_handler_filename(target.name))
        else:
            handler_file = os.path.join(self._repo_dir, to_handler_filename(target.name))

        if os.path.isfile(handler_file):
            with codecs.open(handler_file, 'r', 'utf-8') as f:
                handler = f.read()
            self._notify_load(target, handler, handler_file)

        if handler is None:
            handler = self._create_stub_handler(target, self._decorate)
            handler_dir = os.path.dirname(handler_file)
            if not os.path.isdir(handler_dir):
                os.makedirs(handler_dir)
            with open(handler_file, 'w') as f:
                f.write(handler)
            self._notify_create(target, handler, handler_file)

        entry = (target, handler, handler_file)
        self._handler_by_id[target.identifier] = entry
        self._handler_by_file[handler_file] = entry

        self._ensure_monitor(handler_file)

        return handler

    def _ensure_monitor(self, handler_file):
        handler_dir = os.path.dirname(handler_file)
        monitor = self._repo_monitors.get(handler_dir)
        if monitor is None:
            monitor = frida.FileMonitor(handler_dir)
            monitor.on('change', self._on_change)
            self._repo_monitors[handler_dir] = monitor

    def commit_handlers(self):
        for monitor in self._repo_monitors.values():
            monitor.enable()

    def _on_change(self, changed_file, other_file, event_type):
        if changed_file not in self._handler_by_file or event_type == 'changes-done-hint':
            return
        self._changed_files.add(changed_file)
        self._last_change_id += 1
        change_id = self._last_change_id
        self._reactor.schedule(lambda: self._sync_handlers(change_id), delay=0.05)

    def _sync_handlers(self, change_id):
        if change_id != self._last_change_id:
            return
        changes = self._changed_files.copy()
        self._changed_files.clear()
        for changed_handler_file in changes:
            (target, old_handler, handler_file) = self._handler_by_file[changed_handler_file]
            with codecs.open(handler_file, 'r', 'utf-8') as f:
                new_handler = f.read()
            changed = new_handler != old_handler
            if changed:
                entry = (target, new_handler, handler_file)
                self._handler_by_id[target.identifier] = entry
                self._handler_by_file[handler_file] = entry
                self._notify_update(target, new_handler, handler_file)


class InitScript(object):
    def __init__(self, filename, source):
        self.filename = filename
        self.source = source


class OutputFile(object):
    def __init__(self, filename):
        self._fd = codecs.open(filename, 'wb', 'utf-8')

    def close(self):
        self._fd.close()

    def append(self, message):
        self._fd.write(message)
        self._fd.flush()


class UI(object):
    def on_trace_progress(self, status):
        pass

    def on_trace_warning(self, message):
        pass

    def on_trace_error(self, message):
        pass

    def on_trace_events(self, events):
        pass

    def on_trace_handler_create(self, target, handler, source):
        pass

    def on_trace_handler_load(self, target, handler, source):
        pass


def to_filename(name):
    result = ""
    for c in name:
        if c.isalnum() or c == ".":
            result += c
        else:
            result += "_"
    return result


def to_handler_filename(name):
    full_filename = to_filename(name)
    if len(full_filename) <= 41:
        return full_filename + ".js"
    crc = binascii.crc32(full_filename.encode())
    return full_filename[0:32] + "_%08x.js" % crc


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
