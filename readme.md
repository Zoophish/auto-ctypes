# auto-ctypes

A small Python script that generates bindings for C header files and binaries using ctypes. It's a very simple implementation that uses regular expressions. I made it as a lightweight alternative to automatically create Python bindings for my own projects and avoid writing repetitive code. It is limited to subset of C syntax for simplicity.

**Features**    
- Does basic pre-processing of includes, macros and conditional compilation    
- Generates `ctypes.Structure` derived classes for each type in the header(s) and fills in `_fields_`. Opaque types have no `_field_` elements.    
- Wraps header enums with fake enum class. Enum values are `ctypes.c_int` by default, but can be overriden using C++ colon syntax (doesn't support any other C++ features).    
- Creates function wrappers for functions marked for export in headers. It deduces return and argument types and generates type hints.    
- Parses typedefs for type name aliases    
- Small: ~600 lines of Python    
- It doesn't wrap global variables    

**Installing**

To install the package with PIP:

```cmd
cd ./autoctypes
pip install .
```

Or drop `autoctypes/auto_ctypes.py` into your working directory and invoke the script from the command line.   

**Loading a Library**
```python
import autoctypes

# specify the binary and include path
bin_path = 'bin\\my_lib.dll'
include_path = 'include'

# choose headers to wrap
headers = ["my_lib.h"]

# specify the export macro used in the header
export_tag = 'MY_LIB_EXPORT'

# load the binary and definitions into a clib instance
clib = autoctypes.CLib()
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
# if type is opaque, can only use pointers
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


**Command-Line Usage**   
The script can be used from the command-line (for use in CMake for example).   
```cmd
python ./auto_ctypes.py -gen <header_path> <headers> <bin_path> <export_macro> <output_path> <gen_module_name> [flags]
```

Flags:   
- `--nopkg` Don't make a folder and `__init__.py` with the generated wrapper.
