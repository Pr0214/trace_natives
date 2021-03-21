(function(){function r(e,n,t){function o(i,f){if(!n[i]){if(!e[i]){var c="function"==typeof require&&require;if(!f&&c)return c(i,!0);if(u)return u(i,!0);var a=new Error("Cannot find module '"+i+"'");throw a.code="MODULE_NOT_FOUND",a}var p=n[i]={exports:{}};e[i][0].call(p.exports,function(r){var n=e[i][1][r];return o(n||r)},p,p.exports,r,e,n,t)}return n[i].exports}for(var u="function"==typeof require&&require,i=0;i<t.length;i++)o(t[i]);return o}return r})()({1:[function(require,module,exports){
(function (global){(function (){
"use strict";

class e {
  constructor() {
    this.handlers = new Map, this.stackDepth = new Map, this.traceState = {}, this.nextId = 1, 
    this.started = Date.now(), this.pendingEvents = [], this.flushTimer = null, this.cachedModuleResolver = null, 
    this.cachedObjcResolver = null, this.flush = () => {
      if (null !== this.flushTimer && (clearTimeout(this.flushTimer), this.flushTimer = null), 
      0 === this.pendingEvents.length) return;
      const e = this.pendingEvents;
      this.pendingEvents = [], send({
        type: "events:add",
        events: e
      });
    };
  }
  init(e, t, s, n) {
    const o = global;
    o.stage = e, o.parameters = t, o.state = this.traceState;
    for (const e of s) try {
      (0, eval)(e.source);
    } catch (t) {
      throw new Error(`Unable to load ${e.filename}: ${t.stack}`);
    }
    this.start(n).catch((e => {
      send({
        type: "agent:error",
        message: e.message
      });
    }));
  }
  dispose() {
    this.flush();
  }
  update(e, t, s) {
    const n = this.handlers.get(e);
    if (void 0 === n) throw new Error("Invalid target ID");
    const o = this.parseHandler(t, s);
    n[0] = o[0], n[1] = o[1];
  }
  async start(e) {
    const t = {
      native: new Map,
      java: []
    }, s = [];
    for (const [n, o, a] of e) switch (o) {
     case "module":
      "include" === n ? this.includeModule(a, t) : this.excludeModule(a, t);
      break;

     case "function":
      "include" === n ? this.includeFunction(a, t) : this.excludeFunction(a, t);
      break;

     case "relative-function":
      "include" === n && this.includeRelativeFunction(a, t);
      break;

      case "relative-function-many":
      "include" === n && this.includeRelativeFunctions(a, t);
      break;

     case "imports":
      "include" === n && this.includeImports(a, t);
      break;

     case "objc-method":
      "include" === n ? this.includeObjCMethod(a, t) : this.excludeObjCMethod(a, t);
      break;

     case "java-method":
      s.push([ n, a ]);
      break;

     case "debug-symbol":
      "include" === n && this.includeDebugSymbol(a, t);
    }
    let n, o = !0;
    if (s.length > 0) {
      if (!Java.available) throw new Error("Java runtime is not available");
      n = new Promise(((e, n) => {
        Java.perform((() => {
          o = !1;
          for (const [e, n] of s) "include" === e ? this.includeJavaMethod(n, t) : this.excludeJavaMethod(n, t);
          this.traceJavaTargets(t.java).then(e).catch(n);
        }));
      }));
    } else n = Promise.resolve();
    await this.traceNativeTargets(t.native), o || await n, send({
      type: "agent:initialized"
    }), n.then((() => {
      send({
        type: "agent:started",
        count: this.handlers.size
      });
    }));
  }
  async traceNativeTargets(e) {
    const t = new Map, s = new Map;
    for (const [n, [o, a, r]] of e.entries()) {
      const e = "objc" === o ? s : t;
      let i = e.get(a);
      void 0 === i && (i = [], e.set(a, i)), i.push([ r, ptr(n) ]);
    }
    return await Promise.all([ this.traceNativeEntries("c", t), this.traceNativeEntries("objc", s) ]);
  }
  async traceNativeEntries(e, s) {
    if (0 === s.size) return;
    const n = this.nextId, o = [], a = {
      type: "handlers:get",
      flavor: e,
      baseId: n,
      scopes: o
    };
    for (const [e, t] of s.entries()) o.push({
      name: e,
      members: t.map((e => e[0]))
    }), this.nextId += t.length;
    const {scripts: r} = await t(a);
    let i = 0;
    for (const e of s.values()) for (const [t, s] of e) {
      const e = n + i, o = "string" == typeof t ? t : t[1], a = this.parseHandler(o, r[i]);
      this.handlers.set(e, a);
      try {
        Interceptor.attach(s, this.makeNativeListenerCallbacks(e, a));
      } catch (e) {
        send({
          type: "agent:warning",
          message: `Skipping "${t}": ${e.message}`
        });
      }
      i++;
    }
  }
  async traceJavaTargets(e) {
    const s = this.nextId, n = [], o = {
      type: "handlers:get",
      flavor: "java",
      baseId: s,
      scopes: n
    };
    for (const t of e) for (const [e, {methods: s}] of t.classes.entries()) {
      const t = e.split("."), o = t[t.length - 1], a = Array.from(s.keys()).map((e => [ e, `${o}.${e}` ]));
      n.push({
        name: e,
        members: a
      }), this.nextId += a.length;
    }
    const {scripts: a} = await t(o);
    return new Promise((t => {
      Java.perform((() => {
        let n = 0;
        for (const t of e) {
          const e = Java.ClassFactory.get(t.loader);
          for (const [o, {methods: r}] of t.classes.entries()) {
            const t = e.use(o);
            for (const [e, o] of r.entries()) {
              const r = s + n, i = this.parseHandler(o, a[n]);
              this.handlers.set(r, i);
              const c = t[e];
              for (const e of c.overloads) e.implementation = this.makeJavaMethodWrapper(r, e, i);
              n++;
            }
          }
        }
        t();
      }));
    }));
  }
  makeNativeListenerCallbacks(e, t) {
    const s = this;
    return {
      onEnter(n) {
        s.invokeNativeHandler(e, t[0], this, n, ">");
      },
      onLeave(n) {
        s.invokeNativeHandler(e, t[1], this, n, "<");
      }
    };
  }
  makeJavaMethodWrapper(e, t, s) {
    const n = this;
    return function(...o) {
      return n.handleJavaInvocation(e, t, s, this, o);
    };
  }
  handleJavaInvocation(e, t, s, n, o) {
    this.invokeJavaHandler(e, s[0], n, o, ">");
    const a = t.apply(n, o), r = this.invokeJavaHandler(e, s[1], n, a, "<");
    return void 0 !== r ? r : a;
  }
  invokeNativeHandler(e, t, s, n, o) {
    const a = Date.now() - this.started, r = s.threadId, i = this.updateDepth(r, o);
    t.call(s, ((...t) => {
      this.emit([ e, a, r, i, t.join(" ") ]);
    }), n, this.traceState);
  }
  invokeJavaHandler(e, t, s, n, o) {
    const a = Date.now() - this.started, r = Process.getCurrentThreadId(), i = this.updateDepth(r, o), c = (...t) => {
      this.emit([ e, a, r, i, t.join(" ") ]);
    };
    try {
      return t.call(s, c, n, this.traceState);
    } catch (e) {
      if (void 0 !== e.$h) throw e;
      Script.nextTick((() => {
        throw e;
      }));
    }
  }
  updateDepth(e, t) {
    const s = this.stackDepth;
    let n = s.get(e) ?? 0;
    return ">" === t ? s.set(e, n + 1) : (n--, 0 !== n ? s.set(e, n) : s.delete(e)), 
    n;
  }
  parseHandler(e, t) {
    try {
      const e = (0, eval)("(" + t + ")");
      return [ e.onEnter ?? u, e.onLeave ?? u ];
    } catch (t) {
      return send({
        type: "agent:warning",
        message: `Invalid handler for "${e}": ${t.message}`
      }), [ u, u ];
    }
  }
  includeModule(e, t) {
    const {native: s} = t;
    for (const t of this.getModuleResolver().enumerateMatches(`exports:${e}!*`)) s.set(t.address.toString(), n(t));
  }
  excludeModule(e, t) {
    const {native: s} = t;
    for (const t of this.getModuleResolver().enumerateMatches(`exports:${e}!*`)) s.delete(t.address.toString());
  }
  includeFunction(e, t) {
    const s = r(e), {native: o} = t;
    for (const e of this.getModuleResolver().enumerateMatches(`exports:${s.module}!${s.function}`)) o.set(e.address.toString(), n(e));
  }
  excludeFunction(e, t) {
    const s = r(e), {native: n} = t;
    for (const e of this.getModuleResolver().enumerateMatches(`exports:${s.module}!${s.function}`)) n.delete(e.address.toString());
  }
  includeRelativeFunction(e, t) {
    const s = i(e), n = Module.getBaseAddress(s.module).add(s.offset);
    t.native.set(n.toString(), [ "c", s.module, "sub_" + s.offset.toString(16) ]);
  }
  includeRelativeFunctions(e, t) {
    const s = ii(e);
    n = Module.getBaseAddress(s.module).add(s.offset);
    t.native.set(n.toString(), [ "c", s.module, s.name]);
  }

  includeImports(e, t) {
    let s;
    if (null === e) {
      const e = Process.enumerateModules()[0].path;
      s = this.getModuleResolver().enumerateMatches(`imports:${e}!*`);
    } else s = this.getModuleResolver().enumerateMatches(`imports:${e}!*`);
    const {native: o} = t;
    for (const e of s) o.set(e.address.toString(), n(e));
  }
  includeObjCMethod(e, t) {
    const {native: s} = t;
    for (const t of this.getObjcResolver().enumerateMatches(e)) s.set(t.address.toString(), o(t));
  }
  excludeObjCMethod(e, t) {
    const {native: s} = t;
    for (const t of this.getObjcResolver().enumerateMatches(e)) s.delete(t.address.toString());
  }
  includeJavaMethod(e, t) {
    const s = t.java, n = Java.enumerateMethods(e);
    for (const e of n) {
      const {loader: t} = e, n = h(s, (e => {
        const {loader: s} = e;
        return null !== s && null !== t ? s.equals(t) : s === t;
      }));
      if (void 0 === n) {
        s.push(c(e));
        continue;
      }
      const {classes: o} = n;
      for (const t of e.classes) {
        const {name: e} = t, s = o.get(e);
        if (void 0 === s) {
          o.set(e, l(t));
          continue;
        }
        const {methods: n} = s;
        for (const e of t.methods) {
          const t = d(e), s = n.get(t);
          void 0 === s ? n.set(t, e) : n.set(t, e.length > s.length ? e : s);
        }
      }
    }
  }
  excludeJavaMethod(e, t) {
    const s = t.java, n = Java.enumerateMethods(e);
    for (const e of n) {
      const {loader: t} = e, n = h(s, (e => {
        const {loader: s} = e;
        return null !== s && null !== t ? s.equals(t) : s === t;
      }));
      if (void 0 === n) continue;
      const {classes: o} = n;
      for (const t of e.classes) {
        const {name: e} = t, s = o.get(e);
        if (void 0 === s) continue;
        const {methods: n} = s;
        for (const e of t.methods) {
          const t = d(e);
          n.delete(t);
        }
      }
    }
  }
  includeDebugSymbol(e, t) {
    const {native: s} = t;
    for (const t of DebugSymbol.findFunctionsMatching(e)) s.set(t.toString(), a(t));
  }
  emit(e) {
    this.pendingEvents.push(e), null === this.flushTimer && (this.flushTimer = setTimeout(this.flush, 50));
  }
  getModuleResolver() {
    let e = this.cachedModuleResolver;
    return null === e && (e = new ApiResolver("module"), this.cachedModuleResolver = e), 
    e;
  }
  getObjcResolver() {
    let e = this.cachedObjcResolver;
    if (null === e) {
      try {
        e = new ApiResolver("objc");
      } catch (e) {
        throw new Error("Objective-C runtime is not available");
      }
      this.cachedObjcResolver = e;
    }
    return e;
  }
}

async function t(e) {
  const t = [], {type: n, flavor: o, baseId: a} = e, r = e.scopes.slice().map((({name: e, members: t}) => ({
    name: e,
    members: t.slice()
  })));
  let i = a;
  do {
    const e = [], a = {
      type: n,
      flavor: o,
      baseId: i,
      scopes: e
    };
    let c = 0;
    for (const {name: t, members: s} of r) {
      const n = [];
      e.push({
        name: t,
        members: n
      });
      let o = !1;
      for (const e of s) if (n.push(e), c++, 1e3 === c) {
        o = !0;
        break;
      }
      if (s.splice(0, n.length), o) break;
    }
    for (;0 !== r.length && 0 === r[0].members.length; ) r.splice(0, 1);
    send(a);
    const l = await s("reply:" + i);
    t.push(...l.scripts), i += c;
  } while (0 !== r.length);
  return {
    scripts: t
  };
}

function s(e) {
  return new Promise((t => {
    recv(e, (e => {
      t(e);
    }));
  }));
}

function n(e) {
  const [t, s] = e.name.split("!", 2);
  return [ "c", t, s ];
}

function o(e) {
  const {name: t} = e, [s, n] = t.substr(2, t.length - 3).split(" ", 2);
  return [ "objc", s, [ n, t ] ];
}

function a(e) {
  const t = DebugSymbol.fromAddress(e);
  return [ "c", t.moduleName ?? "", t.name ];
}

function r(e) {
  const t = e.split("!", 2);
  let s, n;
  return 1 === t.length ? (s = "*", n = t[0]) : (s = "" === t[0] ? "*" : t[0], n = "" === t[1] ? "*" : t[1]), 
  {
    module: s,
    function: n
  };
}

function i(e) {
  const t = e.split("!", 2);
  return {
    module: t[0],
    offset: parseInt(t[1], 16)
  };
}
function ii(e) {
  const t = e.split("!", 3);
  return {
    module: t[0],
    offset: parseInt(t[1], 16),
    name:t[2]
  };
}

function c(e) {
  return {
    loader: e.loader,
    classes: new Map(e.classes.map((e => [ e.name, l(e) ])))
  };
}

function l(e) {
  return {
    methods: new Map(e.methods.map((e => [ d(e), e ])))
  };
}

function d(e) {
  const t = e.indexOf("(");
  return -1 === t ? e : e.substr(0, t);
}

function h(e, t) {
  for (const s of e) if (t(s)) return s;
}

function u() {}

const f = new e;

rpc.exports = {
  init: f.init.bind(f),
  dispose: f.dispose.bind(f),
  update: f.update.bind(f)
};

}).call(this)}).call(this,typeof global !== "undefined" ? global : typeof self !== "undefined" ? self : typeof window !== "undefined" ? window : {})

},{}]},{},[1])
//# sourceMappingURL=data:application/json;charset=utf-8;base64,eyJ2ZXJzaW9uIjozLCJzb3VyY2VzIjpbIm5vZGVfbW9kdWxlcy9icm93c2VyLXBhY2svX3ByZWx1ZGUuanMiLCJhZ2VudC50cyJdLCJuYW1lcyI6W10sIm1hcHBpbmdzIjoiQUFBQTs7OztBQ0FBLE1BQU07RUFBTjtJQUNZLEtBQUEsV0FBVyxJQUFJLEtBQ2YsS0FBQSxhQUFhLElBQUksS0FDakIsS0FBQSxhQUF5QixJQUN6QixLQUFBLFNBQVM7SUFDVCxLQUFBLFVBQVUsS0FBSyxPQUVmLEtBQUEsZ0JBQThCLElBQzlCLEtBQUEsYUFBa0IsTUFFbEIsS0FBQSx1QkFBMkM7SUFDM0MsS0FBQSxxQkFBeUMsTUFnZ0J6QyxLQUFBLFFBQVE7TUFNWixJQUx3QixTQUFwQixLQUFLLGVBQ0wsYUFBYSxLQUFLLGFBQ2xCLEtBQUssYUFBYTtNQUdZLE1BQTlCLEtBQUssY0FBYyxRQUNuQjtNQUdKLE1BQU0sSUFBUyxLQUFLO01BQ3BCLEtBQUssZ0JBQWdCLElBRXJCLEtBQUs7UUFDRCxNQUFNO1FBQ04sUUFBQTs7OztFQTdnQlIsS0FBSyxHQUFjLEdBQTZCLEdBQTJCO0lBQ3ZFLE1BQU0sSUFBSTtJQUNWLEVBQUUsUUFBUSxHQUNWLEVBQUUsYUFBYSxHQUNmLEVBQUUsUUFBUSxLQUFLO0lBRWYsS0FBSyxNQUFNLEtBQVUsR0FDakI7T0FDSSxHQUFJLE1BQU0sRUFBTztNQUNuQixPQUFPO01BQ0wsTUFBTSxJQUFJLE1BQU0sa0JBQWtCLEVBQU8sYUFBYSxFQUFFOztJQUloRSxLQUFLLE1BQU0sR0FBTSxPQUFNO01BQ25CLEtBQUs7UUFDRCxNQUFNO1FBQ04sU0FBUyxFQUFFOzs7O0VBS3ZCO0lBQ0ksS0FBSzs7RUFHVCxPQUFPLEdBQW1CLEdBQWM7SUFDcEMsTUFBTSxJQUFVLEtBQUssU0FBUyxJQUFJO0lBQ2xDLFNBQWdCLE1BQVosR0FDQSxNQUFNLElBQUksTUFBTTtJQUdwQixNQUFNLElBQWEsS0FBSyxhQUFhLEdBQU07SUFDM0MsRUFBUSxLQUFLLEVBQVcsSUFDeEIsRUFBUSxLQUFLLEVBQVc7O0VBR3BC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QUFFLEtBQUssTUFBTSxLQUFLO0VBQ3JELE9BQU8sRUFBQyxLQUFLLEdBQVk7OztBQUc3QixTQUFTLEVBQTBCO0VBQy9CLE9BQU0sTUFBRSxLQUFTLElBQ1YsR0FBVyxLQUFjLEVBQUssT0FBTyxHQUFHLEVBQUssU0FBUyxHQUFHLE1BQU0sS0FBSztFQUMzRSxPQUFPLEVBQUMsUUFBUSxHQUFXLEVBQUMsR0FBWTs7O0FBRzVDLFNBQVMsRUFBNkI7RUFDbEMsTUFBTSxJQUFTLFlBQVksWUFBWTtFQUN2QyxPQUFPLEVBQUMsS0FBSyxFQUFPLGNBQWMsSUFBSSxFQUFPOzs7QUFHakQsU0FBUyxFQUEyQjtFQUNoQyxNQUFNLElBQVMsRUFBUSxNQUFNLEtBQUs7RUFFbEMsSUFBSSxHQUFHO0VBU1AsT0FSc0IsTUFBbEIsRUFBTyxVQUNQLElBQUksS0FDSixJQUFJLEVBQU8sT0FFWCxJQUFtQixPQUFkLEVBQU8sS0FBYSxNQUFNLEVBQU8sSUFDdEMsSUFBbUIsT0FBZCxFQUFPLEtBQWEsTUFBTSxFQUFPO0VBR25DO0lBQ0gsUUFBUTtJQUNSLFVBQVU7Ozs7QUFJbEIsU0FBUyxFQUE2QjtFQUNsQyxNQUFNLElBQVMsRUFBUSxNQUFNLEtBQUs7RUFFbEMsT0FBTztJQUNILFFBQVEsRUFBTztJQUNmLFFBQVEsU0FBUyxFQUFPLElBQUk7Ozs7QUFJcEMsU0FBUyxFQUE4QjtFQUNuQyxPQUFPO0lBQ0gsUUFBUSxFQUFNO0lBQ2QsU0FBUyxJQUFJLElBQ1QsRUFBTSxRQUFRLEtBQUksS0FBUyxFQUFDLEVBQU0sTUFBTSxFQUE4Qjs7OztBQUlsRixTQUFTLEVBQThCO0VBQ25DLE9BQU87SUFDSCxTQUFTLElBQUksSUFDVCxFQUFNLFFBQVEsS0FBSSxLQUFZLEVBQUMsRUFBaUMsSUFBVzs7OztBQUl2RixTQUFTLEVBQWlDO0VBQ3RDLE1BQU0sSUFBaUIsRUFBUyxRQUFRO0VBQ3hDLFFBQTRCLE1BQXBCLElBQXlCLElBQVcsRUFBUyxPQUFPLEdBQUc7OztBQUduRSxTQUFTLEVBQVEsR0FBWTtFQUN6QixLQUFLLE1BQU0sS0FBVyxHQUNsQixJQUFJLEVBQVUsSUFDVixPQUFPOzs7QUFLbkIsU0FBUzs7QUE4RlQsTUFBTSxJQUFRLElBQUk7O0FBRWxCLElBQUksVUFBVTtFQUNWLE1BQU0sRUFBTSxLQUFLLEtBQUs7RUFDdEIsU0FBUyxFQUFNLFFBQVEsS0FBSztFQUM1QixRQUFRLEVBQU0sT0FBTyxLQUFLIiwiZmlsZSI6ImdlbmVyYXRlZC5qcyIsInNvdXJjZVJvb3QiOiIifQ==
