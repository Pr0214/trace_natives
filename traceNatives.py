# -*- coding:utf-8 -*-
import os
from idaapi import plugin_t
from idaapi import PLUGIN_PROC
from idaapi import PLUGIN_OK
import ida_nalt
import idaapi
import idautils
import idc



# 获取SO文件名和路径
def getSoPathAndName():
    fullpath = ida_nalt.get_input_file_path()
    filepath,filename = os.path.split(fullpath)
    return filepath,filename

# 获取代码段的范围
def getSegAddr():
    textStart = []
    textEnd = []

    for seg in idautils.Segments():
        if (idc.get_segm_name(seg)).lower() == '.text' or (
        idc.get_segm_name(seg)).lower() == 'text':
            tempStart = idc.get_segm_start(seg)
            tempEnd = idc.get_segm_end(seg)

            textStart.append(tempStart)
            textEnd.append(tempEnd)

    return min(textStart), max(textEnd)


class traceNatives(plugin_t):
    flags = PLUGIN_PROC
    comment = "traceNatives"
    help = ""
    wanted_name = "traceNatives"
    wanted_hotkey = ""

    def init(self):
        print("traceNatives(v0.1) plugin has been loaded.")
        return PLUGIN_OK

    def run(self, arg):
        # 查找需要的函数
        ea, ed = getSegAddr()
        search_result = []
        for func in idautils.Functions(ea, ed):
            try:
                functionName = str(idaapi.ida_funcs.get_func_name(func))
                demangled = idc.demangle_name(functionName,
                                              idc.get_inf_attr(
                                                  idc.INF_SHORT_DN))
                functionName = demangled if demangled else functionName
                if len(list(idautils.FuncItems(func))) > 10:
                    # 如果是thumb模式，地址+1
                    arm_or_thumb = idc.get_sreg(func, "T")
                    if arm_or_thumb:
                        func += 1
                    search_result.append([hex(func), functionName])
            except:
                pass

        so_path, so_name = getSoPathAndName()
        search_result = [f"{so_name}!{a}!{b}" for a, b in search_result]
        search_result = "\n".join(search_result)

        save_path = os.path.join(so_path, so_name.split(".")[0] + ".txt")
        with open(save_path, "w", encoding="utf-8")as F:
            F.write(search_result)

        print("使用方法如下：")
        print(f"frida-trace -UF -z {save_path}")

    def term(self):
        pass


def PLUGIN_ENTRY():
    return traceNatives()
