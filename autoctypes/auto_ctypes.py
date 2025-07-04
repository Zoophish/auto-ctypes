# Copyright Sam Warren 2021
# autoctypes - automatically creates bindings to C binaries & headers.

import ctypes
import os
import string
import re
import types
from inspect import currentframe, getframeinfo


# - - - - utility functions - - - -

def print_error(msg):
    frameinfo = getframeinfo(currentframe().f_back)
    print("[autoctypes] Error, line " + str(frameinfo.lineno) + ": " + msg)


def wrap_function(lib, funcname, restype, argtypes, argnames):
    if lib == None:
        print_error("Cannot load function because no C binary is loaded.")
    func = lib.__getattr__(funcname)
    func.restype = restype
    func.argtypes = argtypes
    func.argnames = argnames
    return func


def is_primitive_ctype(t):
    return issubclass(t, ctypes._SimpleCData) and hasattr(t, '_type_')


def split(s, seps):
    default_sep = seps[0]
    for sep in seps[1:]:
        s = s.replace(sep, default_sep)
    return [i.strip() for i in s.split(default_sep)]


def get_all_enclosed(s, beg, end, inclusive = False):
    pattern = re.escape(beg) + "(.*?)" + re.escape(end)
    if inclusive:
        return [beg + match + end for match in re.findall(pattern, s, re.DOTALL)]
    else:
        return re.findall(pattern, s, re.DOTALL)


# make pointers written in same way for easier parsing
def move_pointer_sig(type_str, name_str):
    if '*' in name_str:
        name_str = name_str.replace('*', '')
        type_str += '*'
    return (type_str, name_str)


# move array signiture into type_str (invalid c syntax but parseable)
def move_array_sig(type_str, name_str):
    if '[' in name_str and ']' in name_str:
        num_str = re.search("\[.*?\]", name_str).group(0)
        type_str += '[' + num_str[1:-1] + ']'
        name_str = name_str.replace(num_str, '')
    return (type_str, name_str)


# convert argument string to list of type names and argument names
def reduce_func_args(arg_str):
    if ',' in arg_str:
        args = [arg.lstrip() for arg in arg_str.split(',')] # remove pre-space
    else:
        args = [arg_str]
    arg_names = [None] * len(args)
    for i in range(0, len(args)): # reduce to list of type names (remove argument names)
        if '(' in args[i] and ')' in args[i]: # probably function pointer
            # function pointer handled differently
            arg_names[i] = re.search("\(\*(.*?)\)", args[i]).group(1)
        else: # regular type
            arg_t = args[i].split(' ')
            if len(arg_t) > 1:
                arg_t = move_pointer_sig(arg_t[0], arg_t[1])
                arg_t = move_array_sig(arg_t[0], arg_t[1])
                arg_names[i] = arg_t[1]
            args[i] = arg_t[0]
    return (args, arg_names)


# desugared representations
multitoken_subs = (
    (r'\blong\s+long(?:\s+int\b)?\b', 'long-long'),
    (r'\blong\s+double\b', 'long-double'),
    (r'\blong(?:\s+int\b)?\b', 'long'),
    (r'\bshort(?:\s+int\b)?\b', 'short'),
    (r'\bchar\b', 'char'),
    (r'\bint\b', 'int'),
    (r'\bfloat\b', 'float'),
    (r'\bdouble\b', 'double'),
    (r'\bbool\b', 'bool'),
    (r'\bvoid\b', 'void'),
    (r'\bwchar_t\b', 'wchar_t'),
    (r'\bsize_t\b', 'size_t'),
)

primitive_ctypes_map = {
    "int": ctypes.c_int,
    "signed-int": ctypes.c_int,
    "unsigned-int": ctypes.c_uint,
    "long": ctypes.c_long,
    "signed-long": ctypes.c_long,
    "unsigned-long": ctypes.c_ulong,
    "long-long": ctypes.c_longlong,
    "signed-long-long": ctypes.c_longlong,
    "unsigned-long-long": ctypes.c_ulonglong,
    "short": ctypes.c_short,
    "signed-short": ctypes.c_short,
    "unsigned-short": ctypes.c_ushort,

    "char": ctypes.c_char,
    "signed-char": ctypes.c_byte,
    "unsigned-char": ctypes.c_ubyte,

    "float": ctypes.c_float,
    "double": ctypes.c_double,
    "long-double": ctypes.c_longdouble,

    "bool": ctypes.c_bool,
    "void": None,

    "size_t": ctypes.c_size_t,
    "wchar_t": ctypes.c_wchar,
}


def desugar_type_str(str):
    str, signed = re.subn(r'\bsigned\b', '', str)  # signedness
    str, unsigned = re.subn(r'\bunsigned\b', '', str)
    str = str.strip()
    if (not str) and (signed or unsigned):
        type_token = 'int'
    else:
        type_token = next((t for r, t in multitoken_subs if re.search(r, str)), 'void')
    if unsigned: type_token = 'unsigned-' + type_token
    elif signed: type_token = 'signed-' + type_token
    return type_token


def desugared_to_prim_ctype(str):
    if str in primitive_ctypes_map:
        return (True, primitive_ctypes_map[str])
    else: return (False, None)


def c_str(s):
    return s.encode('utf-8')


def module_exists(path, name):
    path = os.path.join(path, name)
    b = os.path.isdir(path)
    b = b and os.path.isfile(os.path.join(path, "__init__.py"))
    b = b and os.path.isfile(os.path.join(path, f"{name}.py"))
    return b


def strip_comments(s):
    def replacer(match):
        s = match.group(0)
        if s.startswith('/'):
            return " "  # Replace with a space for potential tokens
        else:
            return ""   # Remove completely 
    return re.sub(r'//.*?$|/\*.*?\*/', replacer, s, flags=re.DOTALL)

# - - - - - - - - - - - - - - -


class CLib():
    def __init__(self):
        self.clib = None
        self.exp_tag = ""
        self.bin_path = ""
        self.include_path = ""
        self.struct_dict = {} # does not store pointer/array types for respective type
        self.enum_dict = {}
        self.func_dict = {}
        self.pre_definitions = {}
        self.unresolved_types = [] # should be empty after headers loaded


    def get_ctype(self, s):
        is_arr = '[' in s and ']' in s
        arr_num = -1
        if is_arr:
            arr_sig = re.search("\[.*?\]", s).group(0)
            arr_num = int(arr_sig[1:-1])
            s = s.replace(arr_sig, '')

        is_ptr = '*' in s
        if is_ptr: s = s.replace('*', '')
        s = s.strip()
        
        t = None
        it = desugared_to_prim_ctype(s) # check for primitive type
        is_primitive = it[0]

        if not is_primitive:
            if s in self.enum_dict: # type is actually enum
                t = ctypes.c_int
            elif s not in self.struct_dict: # pre-declare struct
                self.struct_dict[s] = type(s, (ctypes.Structure,), dict())
                if s not in self.unresolved_types:
                    self.unresolved_types.append(s)
                t = self.struct_dict[s]
            else:
                t = self.struct_dict[s]
            
        else:
            t = it[1]

        if is_arr: t = t * arr_num # make array type
        if is_ptr:
            if is_primitive:
                if s == "void": t = ctypes.c_void_p
                elif s == "char": t = ctypes.c_char_p
                elif s == "wchar": t = ctypes.c_wchar_p
                else: t = ctypes.POINTER(t)
            else: t = ctypes.POINTER(t)
        return t


    def get_fnc_ptr(self, s):
        if re.search(".*?\(\*.*?\)\(.*?\)", s) is not None: # verify is func ptr
            ret_type_name = re.search(".*?(?=\()", s).group(0)
            ret_type = self.get_ctype(ret_type_name)
            arg_str = re.search(ret_type_name + "\(\*.*?\)\((.*?)\)", s).group(1)
            arg_types = None
            if arg_str:
                args, arg_names = reduce_func_args(arg_str)
                arg_types = self.get_arg_types(args)
                return ctypes.CFUNCTYPE(ret_type, *arg_types)
            return ctypes.CFUNCTYPE(ret_type)
        else:
            print_error("Unable to parse as function pointer: " + s)
    

    def get_arg_types(self, str_arg_types):
        if not str_arg_types:
            return None
        arg_types = [] # list of c-types in argument list
        for str_arg in str_arg_types:
            if '(' in str_arg and ')' in str_arg: # probably function pointer
                arg_types.append(self.get_fnc_ptr(str_arg))
            elif str_arg in self.enum_dict:
                arg_types.append(ctypes.c_int) # use int type if enum
            else:
                arg_types.append(self.get_ctype(str_arg))
        return arg_types


    def load_enum(self, e):
        enum_name = re.search("(?<=enum ).*?(?=\s)", e).group(0)
        content = re.search("(?<=\\{).*?(?=\\})", e, re.DOTALL).group(0)

        elements = [el.strip() for el in content.split(',')] # separate items
        enum_values = dict()
        for i in range(0, len(elements)):
            name = ""
            value = None
            if '=' in elements[i]:
                parts = elements[i].split('=')
                name = parts[0].strip()
                value = int(parts[1].strip())
            elif elements[i].strip():
                name = elements[i].strip()
                value = i
            else: continue
            
            enum_values[name] = value

        if enum_name in self.struct_dict: # resolve type as enum
            self.struct_dict.pop(enum_name)
            self.resolve_type(name)
        self.enum_dict[enum_name] = enum_values


    def load_typedef(self, s):
        parts = split(s, string.whitespace)
        if parts[1].strip() == 'struct':
            print("[autoctypes] Global variables not supported")
        elif '(' in s and ')' in s: # probably a func ptr
            f = self.get_fnc_ptr(' '.join(parts[1:]))
            name = re.search(r'\((.*?)\)', s).group(1).replace('*', '')
            self.struct_dict[name] = f
            self.resolve_type(name)
        else: # alias
            type_str = desugar_type_str(' '.join(parts[1:-1]))
            t = self.get_ctype(type_str)
            alias = parts[-1].replace(';', '').strip()
            self.struct_dict[alias] = t
            self.resolve_type(alias)


    def load_func(self, f):
        try:
            exp_str = self.pre_definitions[self.exp_tag]
            f = f.replace(exp_str, '')
            parts = [exp_str] + list(filter(None, split(f, string.whitespace + '()')))

            # 0[export tag] 1[ret type] 2[name] 3[args/junk]

            (parts[1], parts[2]) = move_pointer_sig(parts[1], parts[2]) # move pointer signature into part 1
            
            ret_type = self.get_ctype(parts[1])
            name = parts[2].strip()

            arg_str = re.findall(r'\((.*?)\)', f, re.DOTALL)[0]
            arg_types = None
            arg_names = None
            if arg_str:
                args, arg_names = reduce_func_args(arg_str)    
                arg_types = self.get_arg_types(args)
            self.func_dict[name] = wrap_function(self.clib, name, ret_type, arg_types, arg_names)
        except:
           print_error("Exception occurred loading function: " + f)


    def resolve_type(self, name):
        if name in self.unresolved_types:
            self.unresolved_types.remove(name)


    def load_struct(self, s):
        opaque = True
        if '{' not in s and '}' not in s: # opaque struct wrapper
            opaque = True
            struct_name = re.search("(?<=struct ).*(?=;)", s).group(0).strip()
            self.struct_dict[struct_name] = types.new_class(struct_name, (ctypes.Structure, ), dict())
            self.resolve_type(struct_name) # has a declaration

        else:   # define structure
            opaque = False
            struct_name = re.search("(?<=struct ).*?(?= \{)", s).group(0).strip()

            if struct_name not in self.struct_dict:
                self.struct_dict[struct_name] = types.new_class(struct_name, (ctypes.Structure, ), dict()) # placeholder
            
            struct = self.struct_dict[struct_name]
            
            fields = [] # must set _fields_ attribute with values or class wont behave correctly
            if not opaque:
                content = re.search("\{(.*?)\}", s, re.DOTALL).group(0)[1:-1]
                members = [member.strip() for member in content.split(';')][:-1]
                for member in members:
                    mem_parts = split(member, string.whitespace)
                    type_str = desugar_type_str(' '.join(mem_parts[:-1]))
                    mem_type_name, mem_name = move_pointer_sig(type_str.strip(), mem_parts[-1].strip())
                    mem_type_name, mem_name = move_array_sig(mem_type_name, mem_name)
                    fields.append( (mem_name, self.get_ctype(mem_type_name)) )

            setattr(struct, "_fields_", fields) # add the required _fields_ attribute
            self.resolve_type(struct_name) # has a definition


    def pre_process(self, s):
        lines = s.splitlines()

        def process_block(index, cond=True):
            start = index
            nonlocal lines
            while index < len(lines):
                line = strip_comments(lines[index])
                line = line = re.sub(r'^\s*#\s+', '#', line)  # handle cmake's odd formatting
                if cond: # don't bother processing lines that are inactive
                    for k in self.pre_definitions:
                        if self.pre_definitions[k]:
                            line = lines[index] = re.sub(fr'\b{k}\b', self.pre_definitions[k], line)
                comp = line.split(None, 3)
                if len(comp) == 0:
                    index += 1
                    continue
                # every ifdef block is iterated over, regardless of whether the block condition is true
                # this is to handle every #endif or #else
                elif "#ifdef" in comp[0] or "#ifndef" in comp[0]:
                    blk_start = index
                    condition = ("#ifdef" in comp[0] and comp[1] in self.pre_definitions) or \
                                ("#ifndef" in comp[0] and comp[1] not in self.pre_definitions)
                    index += 1
                    # if the condition is true, process that block
                    if_block, index = process_block(index, condition)
                    else_block = []
                    if index < len(lines) and "#else" in lines[index]:
                        index += 1
                        else_block, index = process_block(index, not condition)
                    if condition:
                        lines[blk_start:index+1] = if_block
                        index = blk_start + len(if_block)
                    else:
                        lines[blk_start:index+1] = else_block
                        index = blk_start + len(else_block)
                elif "#endif" in comp[0] or '#else' in comp[0]:
                    return lines[start:index], index
                elif cond: # only do this pre-processing logic if the block exists
                    if '#include' in comp[0]:
                        path = comp[1].strip()[1:-1]
                        with open(os.path.join(self.include_path, path), 'r') as file:
                            f_lines = self.pre_process(file.read())
                            lines = lines[:index] + f_lines + lines[index + 1:]
                            index += len(f_lines)
                    elif "#define" in comp[0]:
                        self.pre_definitions[comp[1]] = ' '.join(comp[2:]) if len(comp) > 2 else ''
                        lines = lines[:index] + lines[index + 1:]
                    else: index += 1
                else:
                    index += 1
            return lines, index
        result, _ = process_block(0)
        return result


    @staticmethod
    def find_structs(s):
        defined = re.findall("struct [^;.]*?\{.*?\};", s, re.DOTALL)
        opaques = re.findall("struct\\s+\\S+;", s)
        return defined + opaques


    @staticmethod
    def find_enums(s):
        return get_all_enclosed(s, "enum ", "};", True)


    @staticmethod
    def find_funcs(s, exp_tag):
        return get_all_enclosed(s, exp_tag, ';', True)
                

    @staticmethod
    def find_typedefs(s):
        return get_all_enclosed(s, 'typedef', ';', True)


    def define(self, macro, value = ''):
        self.pre_definitions[macro] = value

    def load_header(self, path):
        file = open(path, 'r')
        fstr = file.read()
        fstr = '\n'.join(self.pre_process(fstr))
        fstr = re.sub(r'\b(const|volatile)\s+', '', fstr)  # disregard qualifiers
        # for sub in multitoken_types_subs:  # handle types with spaces
        #     fstr = re.sub(sub[0], sub[1], fstr)
        struct_definitions = self.find_structs(fstr)
        typedef_declarations = self.find_typedefs(fstr)
        enum_definitions = self.find_enums(fstr)
        func_declarations = self.find_funcs(fstr, self.pre_definitions[self.exp_tag])
        file.close()
        [self.load_enum(e) for e in enum_definitions]
        [self.load_struct(s) for s in struct_definitions]
        [self.load_typedef(s) for s in typedef_declarations]
        [self.load_func(f) for f in func_declarations]
        
    
    def load_lib(self, bin_path, include_path, headers, export_tag):
        self.clib = ctypes.CDLL(bin_path)
        self.exp_tag = export_tag
        self.bin_path = bin_path
        self.include_path = include_path

        for h in headers:
            path = os.path.join(include_path, h)
            self.load_header(path)
        return True


    def ex(self, func_name, *params):
        try:
            return (self.func_dict[func_name](*params)) # call function
        except Exception as e:
            print("Error: ctypes function: " + func_name + "():")
            print(e)

    
    def enum(self, enum_name, item_name):
        return self.enum_dict[enum_name][item_name]


    # -------------- module generator ---------------

    @staticmethod
    def get_type_str(t):
        if t is None: return "None"
        is_ptr = hasattr(t, 'contents')
        is_arr = hasattr(t, '_length_')
        is_func_ptr = hasattr(t, '_argtypes_')
        if is_func_ptr:
            restype = CLib.get_type_str(t._restype_)
            if len(t._argtypes_) != 0:
                argstr = ""
                for i, argt in enumerate(t._argtypes_) or []:
                    argstr +=  CLib.get_type_str(argt)
                    if i != (len(t._argtypes_) - 1): argstr += ", "
                return f"ctypes.CFUNCTYPE({restype}, {argstr})"
            return f"ctypes.CFUNCTYPE({restype})"
        if is_arr:
            length = t._length_
        if is_ptr or is_arr:
            t = t._type_
        if t.__module__ == __name__ or t.__module__ == 'types':
            tstr = t.__name__
        else:
            tstr = f"{t.__module__}.{t.__name__}"
        if is_ptr: # pointer
            return f"ctypes.POINTER({tstr})"
        if is_arr: # array
            return f"{tstr} * {length}"
        return tstr


    @staticmethod
    def get_struct_str(c):
        s = "class " + c.__name__.strip() + "(ctypes.Structure):" + "\n\t"
        if hasattr(c, '_fields_'): field_size = len(c._fields_)
        else: field_size = 0
        if field_size > 0:
            s += "_fields_ = [" + "\n\t"
            for i, f in enumerate(c._fields_):
                tstr = CLib.get_type_str(f[1])
                s += "\t(" + '"' + f[0] + '"' + ", " + tstr
                if i == (field_size - 1): s += ")\n\t"
                else: s += "),\n\t"
            s += "]"
        else:
            s += "pass"
        return s


    def gen_structs(self):
        s = ""
        for c in self.struct_dict:
            t = self.struct_dict[c]
            if is_primitive_ctype(t) or hasattr(t, 'argtypes'): # primitive alias or func prototype
                s += f"{c} = {CLib.get_type_str(t)}\n\n"
            else:
                s += self.get_struct_str(t) + "\n\n"
        return s


    def gen_enums(self):
        s = ""
        for e_name, e_values in self.enum_dict.items():
            s += f"class {e_name}():\n"
            for v_name, v_value in e_values.items():
                s += f"\t{v_name} = {str(v_value)} \n"
            s += '\n'
        return s


    @staticmethod
    def get_func_str(name, f):
        args_in = ""
        args = ""
        argt = ""
        restype = CLib.get_type_str(f.restype)
        if f.argtypes is not None:
            for i in range(0, len(f.argtypes)):
                t = f.argtypes[i]
                tstr = CLib.get_type_str(t)
                argt += tstr
                args += f.argnames[i] + f" :{tstr}"
                args_in += f.argnames[i]
                if i != (len(f.argtypes) - 1):
                    args += ", "
                    args_in += ", "
                    argt += ", "
        s = ""
        if f.restype is not None: s += f"__clib.{name}.restype = {restype}" + '\n'
        s += f"__clib.{name}.argtypes = [{argt}]" + '\n'
        if f.restype is not None:
            s += f"def {name}({args}) -> {restype}:" + "\n\t"
        else:
            s += f"def {name}({args}):" + "\n\t"
        if f.restype is not None:
            s += f"return __clib.{name}({args_in})"
        else:
            s += f"__clib.{name}({args_in})"
        return s


    def gen_funcs(self):
        s = ""
        for f in self.func_dict:
            s += self.get_func_str(f, self.func_dict[f])
            s += "\n\n\n"
        return s



    # convert loaded library to Python module
    def gen_module(self, path, name, no_pkg = False):
        print(f"[autoctypes] Generating module {name}")
        if not no_pkg: path = os.path.join(path, name)
        try: os.mkdir(path)
        except OSError: pass # dir exists
        s = "# generated by autoctypes" + '\n'
        s += "import ctypes" + '\n'
        s += "import os.path" + "\n\n"
        s += "__file_path = os.path.dirname(os.path.abspath(__file__))" + '\n'
        s += f"__bin_path = os.path.join(__file_path, r'{os.path.relpath(self.bin_path, path)}')" + '\n'
        s += "__clib = ctypes.CDLL(__bin_path)" + "\n\n\n"
        s += self.gen_enums()
        s += self.gen_structs()
        s += self.gen_funcs()
        file = open(os.path.join(path, f"{name}.py"), 'w')
        file.write(s)
        file.close()
        if not no_pkg:
            file = open(os.path.join(path, "__init__.py"), 'w')
            file.close()
        print(f"[autoctypes] Module generated at {path}")


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print("Usage: -gen <header_path> <headers> <bin_path> <export_macro> <output_path> <gen_module_name> --[nopkg/]")
        sys.exit(1)
    if sys.argv[1] == '-gen':
        header_path, headers_arg, bin_path, export_macro, output_path, gen_module_name = sys.argv[2:8]
        headers = [h.strip() for h in headers_arg.strip('"').split(',') if h.strip()]
        clib = CLib()
        clib.exp_tag = export_macro
        clib.load_lib(os.path.normpath(bin_path), os.path.normpath(header_path), headers, export_macro)
        no_pkg = "--nopkg" in sys.argv
        clib.gen_module(os.path.normpath(output_path), gen_module_name, no_pkg)
    else:
        print(f"{sys.argv[0]} unrecognised argument.")
