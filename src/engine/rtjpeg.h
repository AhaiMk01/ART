// -*- C++ -*-
#pragma once

#include <exception>
#include <stdio.h>

namespace art { namespace engine {
class ProgressListener;
}}

#ifdef __cplusplus
extern "C" {
#endif

#include <jpeglib.h>

struct rt_jpeg_error_mgr {
    struct jpeg_error_mgr pub;
    const char *filename;
    art::engine::ProgressListener *pl;
};

extern GLOBAL(struct jpeg_error_mgr *)
    rt_jpeg_std_error(rt_jpeg_error_mgr *err, const char *filename,
                      art::engine::ProgressListener *pl);

#ifdef __cplusplus
}
#endif

struct rt_jpeg_error: public std::exception {
    const char *what() const throw() { return ""; }
};
