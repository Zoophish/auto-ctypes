# auto-ctypes

A small Python script that automatically generates bindings for C header files and binaries using ctypes. It's a very simple implementation that uses regular expressions. I made it as a lightweight alternative to automatically create Python bindings for my own projects and avoid writing repetitive code.

**Features**    
- Generates `ctypes.Structure` derived classes for each type in the header(s) and automatically fills in `_fields_`. Opaque types have no `_field_` elements.    
- Wraps header enums with fake enum class. Enum values are `ctypes.c_int` by default, but can be overriden using C++ colon syntax (doesn't support any other C++ features).    
- Creates function wrappers for exported functions in header(s). It deduces return and argument types automatically and generates type hints.    
- Does basic pre-processing of includes, macros and conditional compilation     
- Small: ~500 lines of Python    
- It doesn't wrap global variables as I don't use these.    

**Loading a Library**
```python
from .autoctypes import auto_ctypes as actypes

# specify the binary and include path
bin_path = 'bin\\my_lib.dll'
include_path = 'include'

# choose headers to wrap
headers = ["my_lib.h"]

# specify the export macro used in the header
export_tag = 'MY_LIB_EXPORT'

# load the binary and definitions into a clib instance
clib = actypes.CLib()
# add a macro to the pre-processor
clib.define('_WIN32')
# load everything with one function
clib.load_lib(bin_path, header_path, headers, export_tag)

# generate the python module called my_lib
clib.gen_module(main_path, "my_lib")

```
**Generated Module Example**    
Reading the generated module, it is hopefully quite clear how the headers get converted to Python.
```python
from .my_lib import my_lib

# calling functions (same name as in header)
output = my_lib.my_function(100)

# using enums (same names as in header)
value = my_lib.ShapeEnum.SQUARE

# using types (same names as in header)
# if type is opaque, can only use pointers to 
my_type_instance = my_lib.MyType()
my_type_instance.int_member = 9
```

**Using Library Instance Directly**
```python
# alternatively use the clib instance directly to use the library without creating a python module
value1 = clib.ex('my_function', 100)
value2 = clib.enum('ShapeEnum', 'SQUARE')
my_type_instance = clib.struct_dict['MyType']()
```

Sam Warren 2024