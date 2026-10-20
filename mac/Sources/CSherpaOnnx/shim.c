// The sherpa-onnx C API header (vendored from k2-fsa/sherpa-onnx v1.13.8, Apache-2.0) gives Swift
// the config and result structs. The functions are looked up at run time with dlsym from the
// dylib that install.sh puts in the app bundle, so building and testing need no binary.
#include "c-api.h"
