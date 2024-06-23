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
    print("AutoCtypes Error, line " + str(frameinfo.lineno) + ": " + msg)


def wrap_function(lib, funcname, restype, argtypes, argnames):
    if lib == None:
        print_error("Cannot load function because no C binary is loaded.")
    func = lib.__getattr__(funcname)
    func.restype = restype
    func.argtypes = argtypes
    func.argnames = argnames
    return func


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
            arg_t = move_pointer_sig(arg_t[0], arg_t[1])
            arg_t = move_array_sig(arg_t[0], arg_t[1])
            args[i] = arg_t[0]
            arg_names[i] = arg_t[1]
    return (args, arg_names)


integral_ctypes_regex = [
    ("int(?!.)", ctypes.c_int),
    ("unsigned(?!.)", ctypes.c_uint),
    ("char(?!.)", ctypes.c_char),
    ("float", ctypes.c_float),
    ("bool", ctypes.c_bool),
    ("size_t", ctypes.c_size_t),
    ("void(?!.)", None)]


def str_to_integral_ctype(s):
    post = "[\*\[\]]?"
    for i in range(0, len(integral_ctypes_regex)):
        if re.search(integral_ctypes_regex[i][0] + post, s) is not None:
            return (True, integral_ctypes_regex[i][1])
    return (False, None)


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
        it = str_to_integral_ctype(s) # check for integral type
        is_integral = it[0]

        if not is_integral:
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
            if is_integral:
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
            else:
                name = elements[i].strip()
                value = i
            
            enum_values[name] = value

        if enum_name in self.struct_dict: # resolve type as enum
            self.struct_dict.pop(enum_name)
            self.resolve_type(name)
        self.enum_dict[enum_name] = enum_values


    def load_func(self, f):
        try:
            exp_str = self.pre_definitions[self.exp_tag]
            f = f.replace(exp_str, '')
            raw_parts = split(f, string.whitespace + '(')
            parts = [exp_str] + list(filter(None, raw_parts))
            # 0[export tag] 1[ret type] 2[name] 3[args/junk]

            (parts[1], parts[2]) = move_pointer_sig(parts[1], parts[2]) # move pointer signature into part 1
            
            ret_type = self.get_ctype(parts[1])
            name = parts[2].strip()

            arg_str = re.search("\(.*\)", f).group(0)[1:-1] # arguments
            arg_types = None
            arg_names = None
            if arg_str:
                args, arg_names = reduce_func_args(arg_str)    
                arg_types = self.get_arg_types(args)
            self.func_dict[name] = wrap_function(self.clib, name, ret_type, arg_types, arg_names)
        except:
           print_error("Could not load function: " + f)


    def resolve_type(self, name):
        if name in self.unresolved_types:
            self.unresolved_types.remove(name)


    def load_struct(self, s):
        if '{' not in s and '}' not in s: # opaque struct wrapper
            struct_name = re.search("(?<=struct ).*(?=;)", s).group(0)
            self.struct_dict[struct_name] = types.new_class(struct_name, (ctypes.Structure, ), dict())
            self.resolve_type(struct_name) # has a declaration

        else:   # define structure
            struct_name = re.search("(?<=struct ).*?(?= \{)", s).group(0)

            if struct_name not in self.struct_dict:
                self.struct_dict[struct_name] = types.new_class(struct_name, (ctypes.Structure, ), dict()) # placeholder
            
            struct = self.struct_dict[struct_name]
            
            fields = [] # must set _fields_ attribute with values or class wont behave correctly
            content = re.search("\{(.*?)\}", s, re.DOTALL).group(0)[1:-1]
            members = [member.strip() for member in content.split(';')][:-1]
            for member in members:
                mem_parts = split(member, string.whitespace)
                mem_type_name = mem_parts[0].strip()
                mem_name = mem_parts[1].strip()
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
        out = get_all_enclosed(s, "enum ", "};", True)
        return out


    @staticmethod
    def find_funcs(s, exp_tag):
        out = get_all_enclosed(s, exp_tag, ';', True)
        return out

    def define(self, macro, value = ''):
        self.pre_definitions[macro] = value

    def load_header(self, path):
        file = open(path, 'r')
        fstr = file.read()
        fstr = '\n'.join(self.pre_process(fstr))
        struct_definitions = self.find_structs(fstr)
        enum_definitions = self.find_enums(fstr)
        func_declarations = self.find_funcs(fstr, self.pre_definitions[self.exp_tag])
        file.close()
        [self.load_enum(e) for e in enum_definitions]
        [self.load_struct(s) for s in struct_definitions]
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
            restype = t._restype_.__name__ if t._restype_ else "None"
            if len(t._argtypes_) != 0:
                argstr = ""
                for i, argt in enumerate(t._argtypes_) or []:
                    argstr += argt.__name__
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
        s = "class " + c.__name__ + "(ctypes.Structure):" + "\n\t"
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
            struct = self.struct_dict[c]
            s += self.get_struct_str(struct) + "\n\n"
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
    def gen_module(self, path, name):
        print(f"[autoctypes] Generating module {name}")
        path = os.path.join(path, name)
        try: os.mkdir(path)
        except OSError: pass # dir exists
        s = "# generated by autoctypes" + '\n'
        s += "import ctypes" + '\n'
        s += "import os.path" + "\n\n"
        s += f"__bin_path = os.path.normpath(r'{self.bin_path}')" + '\n'
        s += "__clib = ctypes.CDLL(__bin_path)" + "\n\n\n"
        s += self.gen_enums()
        s += self.gen_structs()
        s += self.gen_funcs()
        file = open(os.path.join(path, f"{name}.py"), 'w')
        file.write(s)
        file.close()
        file = open(os.path.join(path, "__init__.py"), 'w')
        file.close()
        print("[autoctypes] Module generated")