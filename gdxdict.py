# Copyright (c) 2011 Incremental IP Limited
# see LICENSE for license information

import gdxcc
import gdxx
import sys
import string


#- Data ------------------------------------------------------------------------

level_names = [ ".l", ".m", ".lo", ".ub", ".scale" ]

type_codes = {
    "set": 0,
    "parameter": 1,
    "scalar": 1,
    "variable": 2,
    "equation": 3,
    "alias": 4,
}

def get_type_code(typename):
    return type_codes[string.lower(typename)]


GMS_SV_PINF = 3e300
GMS_SV_MINF = 4e300

default_variable_fields = [
#     .l   .m           .lo         .ub  .scale
    [ 0.0, 0.0,         0.0,         0.0, 1.0 ],    # unknown
    [ 0.0, 0.0,         0.0,         1.0, 1.0 ],    # binary
    [ 0.0, 0.0,         0.0,       100.0, 1.0 ],    # integer
    [ 0.0, 0.0,         0.0, GMS_SV_PINF, 1.0 ],    # positive
    [ 0.0, 0.0, GMS_SV_MINF,         0.0, 1.0 ],    # negative
    [ 0.0, 0.0, GMS_SV_MINF, GMS_SV_PINF, 1.0 ],    # free
    [ 0.0, 0.0,         0.0, GMS_SV_PINF, 1.0 ],    # sos1
    [ 0.0, 0.0,         0.0, GMS_SV_PINF, 1.0 ],    # sos2
    [ 0.0, 0.0,         1.0, GMS_SV_PINF, 1.0 ],    # semicont
    [ 0.0, 0.0,         1.0,       100.0, 1.0 ]     # semiint
]


#- New symbol object without a file --------------------------------------------

def new():
    symbols = {}

    symbol_info = {}
    symbols["__symbol_info"] = symbol_info

    # read the universal set
    universal_dict = {}
    universal_order = []
    universal_desc = []
    symbols["__universal_dict"] = {}
    symbols["__universal_order"] = []
    symbols["__universal_desc"] = []
    symbol_info["__universal"] = {}

    return symbols


#- Read a GDX file -------------------------------------------------------------

def get_symbol(H, d, name, typename, values):
    if typename == "Set":
        d[name] = True
    else:
        d[name] = values[gdxcc.GMS_VAL_LEVEL]

    if typename == "Variable" or typename == "Equation":
        if not "__limits" in d:
            d["__limits"] = {}
        limits = d["__limits"]
        slimits = {}
        limits[name] = slimits
        for i in range(5):
            slimits[level_names[i]] = values[i]

    if typename == "Set":
        ret, description, node = gdxcc.gdxGetElemText(H, int(values[gdxcc.GMS_VAL_LEVEL]))
        if ret != 0:
            if not "__desc" in d:
                d["__desc"] = {}
            d["__desc"][name] = description


def visit_domains(current, keys, index):
    for k in current:
        if k.startswith("__"): continue
        keys[index][k] = True
        v = current[k]
        if type(v) == dict:
            visit_domains(v, keys, index+1)


def guess_domains(symbols):
    # We don't always get symbol domains from GDX (in 23.7.2 and below
    # gdxSymbolGetDomain doesn't work and otherwise, some GDX files don't seem
    # to contain this information).  So here we try to guess

    symbol_info = symbols["__symbol_info"]

    # First, find all the symbols in all the one-dimensional sets, but map it
    # backwards so we have a map from every set key back to all the sets its in
    set_map = {}
    for k in symbols:
        if k.startswith("__"): continue
        info = symbol_info[k]
        if info["type"] == gdxcc.GMS_DT_SET and info["dims"] == 1:
            symbol = symbols[k]
            for e in symbol:
                if not e in set_map:
                    set_map[e] = {}
                set_map[e][k] = True

    # Then run through all the symbols trying to guess any missing domains
    for k in symbols:
        if k.startswith("__"): continue
        info = symbol_info[k]
        if info["dims"] > 0:
            keys = [{} for i in range(info["dims"])]
            # Enumerate all the keys the symbol uses on each of its dimensions
            visit_domains(symbols[k], keys, 0)
            for i in range(info["dims"]):
                if info["domain"][i]["key"] != "*": continue
                # For each dimension that currently has '*' as it's domain,
                # work out all the possible sets
                pd = None
                for j in keys[i]:
                    if pd == None:
                        pd = {}
                        if j in set_map:
                            for s in set_map[j]: pd[s] = True
                    else:
                        remove = []
                        for s in pd:
                            if not s in set_map[j]: remove.append(s)
                        for r in remove: del pd[r]

                # If the symbol is a set itself, then we probably found that, but we don't want it
                if pd and k in pd: del pd[k]
                if pd and len(pd) > 0:
                    # If we found more than one possible set, pick the shortest
                    # one: our guess is that the set is the smallest set that
                    # contains all the keys that appear in this dimension
                    smallest_set = None
                    length = 1e9 # Can you get DBL_MAX in Python?  A billion out to be enough for anyone.
                    min_length = 0
                    # If we're working with a set, we don't want to pick a set
                    # with the exact same length - we want this to be a subset
                    # of a longer set
                    if info["type"] == gdxcc.GMS_DT_SET:
                        min_length = len(keys[i])
                    for s in pd:
                        l = symbol_info[s]["records"]
                        if l < length and l > min_length:
                            length = l
                            smallest_set = s
                    if smallest_set:
                        info["domain"][i] = { "index":symbol_info[smallest_set]["number"], "key":smallest_set }


def guess_ancestor_domains(symbols):
    symbol_info = symbols["__symbol_info"]
    set_map = {}
    for k in symbols:
        if k.startswith("__"): continue
        info = symbol_info[k]
        if info["dims"] == 0: continue
        for i in range(info["dims"]):
            ancestors = [info["domain"][i]["key"]]
            while ancestors[-1] != '*':
                ancestors.append(symbol_info[ancestors[-1]]["domain"][0]["key"])
            info["domain"][i]["ancestors"] = ancestors


def read(filename, gams_dir):
    H = gdxx.open(gams_dir)
    assert gdxcc.gdxOpenRead(H, filename)[0], "Couldn't open %s" % filename

    symbols = {}

    info = gdxx.file_info(H)
    for k in info:
        symbols["__" + k] = info[k]

    symbol_info = {}
    symbols["__symbol_info"] = symbol_info

    # read the universal set
    universal_dict = {}
    universal_order = []
    universal_desc = []
    symbols["__universal_dict"] = universal_dict
    symbols["__universal_order"] = universal_order
    symbols["__universal_desc"] = universal_desc
    sinfo = gdxx.symbol_info(H, 0)
    symbol_info["__universal"] = {}
    for k in sinfo:
        symbol_info["__universal"][k] = sinfo[k]
    ok, records = gdxcc.gdxDataReadStrStart(H, 0)
        
    for i in range(records):
        ok, elements, values, afdim = gdxcc.gdxDataReadStr(H)
        if not ok: raise gdxx.GDX_error(H, "Error in gdxDataReadStr")
        key = elements[0]
        ret, description, node = gdxcc.gdxGetElemText(H, int(values[gdxcc.GMS_VAL_LEVEL]))
        if ret == 0: description = None
        universal_dict[key] = i
        universal_order.append(key)
        universal_desc.append(description)

    # Read all the other symbols
    for i in range(1, info["symbol_count"]+1):

        sinfo = gdxx.symbol_info(H, i)
        symbol_info[sinfo["name"]] = {}
        for k in sinfo:
            symbol_info[sinfo["name"]][k] = sinfo[k]

        ok, records = gdxcc.gdxDataReadStrStart(H, i)
        
        if sinfo["dims"] > 0:
            symbols[sinfo["name"]] = {}
        
        for i in range(records):
            ok, elements, values, afdim = gdxcc.gdxDataReadStr(H)
            if not ok: raise gdxx.GDX_error(H, "Error in gdxDataReadStr")
            if sinfo["dims"] == 0:
                get_symbol(H, symbols, sinfo["name"], sinfo["typename"], values)
            else:
                symbol = symbols[sinfo["name"]]
                current = symbol
                for d in range(sinfo["dims"]-1):
                    key = elements[d]
                    if not key in current:
                        current[key] = {}
                    current = current[key]
                key = elements[sinfo["dims"]-1]
                get_symbol(H, current, key, sinfo["typename"], values)

    gdxcc.gdxClose(H)
    gdxcc.gdxFree(H)

    guess_domains(symbols)
    guess_ancestor_domains(symbols)

    return symbols


#- Write a GDX file ------------------------------------------------------------


values = gdxcc.doubleArray(gdxcc.GMS_VAL_MAX)


def set_symbol(H, d, name, typename, userinfo, values, dims):
    if typename == "Set":
        text_index = 0
        if "__desc" in d and name in d["__desc"]:
            ret, text_index = gdxcc.gdxAddSetText(H, d["__desc"][name])
        values[gdxcc.GMS_VAL_LEVEL] = float(text_index)
    else:
        values[gdxcc.GMS_VAL_LEVEL] = d[name]

    if (typename == "Variable" or typename == "Equation") and "__limits" in d and name in d["__limits"]:
        limits = d["__limits"][name]
        for i in range(1, 5):
            ln = level_names[i]
            if ln in limits:
                values[i] = limits[ln]

    gdxcc.gdxDataWriteStr(H, dims + [name], values)


def write_symbol(H, typename, userinfo, s, dims):
    for k in s:
        if k.startswith("__"): continue
        s2 = s[k]
        if type(s2) == dict:
            write_symbol(H, typename, userinfo, s2, dims + [k])
        else:
            set_symbol(H, s, k, typename, userinfo, values, dims)


def write(symbols, filename, gams_dir):
    H = gdxx.open(gams_dir)
    assert gdxcc.gdxOpenWrite(H, filename, "gdxdict.py")[0], "Couldn't open %s" % filename

    symbol_info = symbols["__symbol_info"]

    # write the universal set
    gdxcc.gdxUELRegisterRawStart(H)
    for i in range(len(symbols["__universal_order"])):
        gdxcc.gdxUELRegisterRaw(H, symbols["__universal_order"][i])
    gdxcc.gdxUELRegisterDone(H)

    for k in symbols:
        if k.startswith("__"): continue
        symbol = symbols[k]
        info = symbol_info[k]
        if type(symbol) != dict:
            if not gdxcc.gdxDataWriteStrStart(H, k, info["description"], 0, get_type_code(info["typename"]), info["userinfo"]):
                raise gdxx.GDX_error(H, "couldn't start writing data")
            set_symbol(H, symbols, k, info["typename"], info["userinfo"], values, [])
            gdxcc.gdxDataWriteDone(H)
        else:
            if not gdxcc.gdxDataWriteStrStart(H, k, info["description"], info["dims"], get_type_code(info["typename"]), info["userinfo"]):
                raise gdxx.GDX_error(H, "couldn't start writing data")
            write_symbol(H, info["typename"], info["userinfo"], symbol, [])
            gdxcc.gdxDataWriteDone(H)

    gdxcc.gdxClose(H)
    gdxcc.gdxFree(H)


#- Setting symbol info ---------------------------------------------------------

def add_UEL(symbols, name, description=None):
    if name not in symbols["__universal_dict"]:
        symbols["__universal_dict"][name] = len(symbols["__universal_order"])
        symbols["__universal_order"].append(name)
        if description: symbols["__universal_desc"].append(description)


def merge_UELs(s1, s2):
    for i in range(len(s2["__universal_order"])):
        add_UEL(s1, s2["__universal_order"][i], s2["__universal_desc"][i])


def get_symbol_info(symbols, name):
    if not "__symbol_info" in symbols:
        symbols["__symbol_info"] = {}
    if not name in symbols["__symbol_info"]:
        if name == '*':
            symbols["__symbol_info"][name] = {
                "dims": 1,
                "type": gdxcc.GMS_DT_SET,
                "typename": "Set",
                "description": "",
                "userinfo": 0,
                "records": len(symbols["__universal_order"])
                }
        else:
            symbols["__symbol_info"][name] = {
                "dims": 0,
                "type": gdxcc.GMS_DT_PAR,
                "typename": "Parameter",
                "description": "",
                "userinfo": 0
                }
    return symbols["__symbol_info"][name]


def set_description(symbols, name, d):
    get_symbol_info(symbols, name)["description"] = d


def set_type(symbols, name, t):
    if type(t) == str:
        typename = t
        typecode = get_type_code(t)
    else:
        typecode = t
        typename = gdxx.symbol_type_text[t]
    
    s = get_symbol_info(symbols, name)
    s["type"] = typecode
    s["typename"] = typename


def get_type(symbols, name):
    i = get_symbol_info(symbols, name)
    return i["typename"], i["type"]


def set_dims(symbols, name, d):
    get_symbol_info(symbols, name)["dims"] = d


def get_dims(symbols, name):
    return get_symbol_info(symbols, name)["dims"]


#- "pretty"ish printing --------------------------------------------------------

def _print_symbol(k, s, dims):
    if type(s) == dict:
        for k2 in s:
            _print_symbol(k2, s[k2], dims + [k])
    else:
        print dims + [k], s


def print_symbol(name, s):
    _print_symbol(name, s, [])


#- main ------------------------------------------------------------------------

class Usage(Exception):
    def __init__(self, msg):
        self.msg = msg

def main(argv=None):
    if argv is None:
        argv = sys.argv
    try:
        if len(sys.argv) < 3 or len(sys.argv) > 4:
            raise Usage("Wrong number of arguments")

        input_gdx = sys.argv[1]
        output_gdx = sys.argv[2]
        gams_dir = None
        if len(sys.argv) == 4:
            gams_dir = sys.argv[3]
            
        symbols = read(input_gdx, gams_dir)
        write(symbols, output_gdx, gams_dir)

    except Usage, err:
        print >>sys.stderr, "Error: %s" % err.msg
        print >>sys.stderr, "Usage: %s <GDX input file> <GDX output file> [GAMS system directory]" % sys.argv[0]
        return 2
    except gdxx.GDX_error, err:
        print >>sys.stderr, "GDX Error: %s" % err.msg
        return 2

    return 1


if __name__ == "__main__":
    sys.exit(main())


#- EOF -------------------------------------------------------------------------
