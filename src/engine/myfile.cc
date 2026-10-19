/*
 *  This file is part of RawTherapee.
 *
 *  Copyright (c) 2004-2010 Gabor Horvath <hgabor@rawtherapee.com>
 *
 *  RawTherapee is free software: you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation, either version 3 of the License, or
 *  (at your option) any later version.
 *
 *  RawTherapee is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *  GNU General Public License for more details.
 *
 *  You should have received a copy of the GNU General Public License
 *  along with RawTherapee.  If not, see <http://www.gnu.org/licenses/>.
 */
#include "myfile.h"
#include <cstdarg>
#include <cstdlib>
#include <glibmm.h>
#ifndef WIN32
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#endif

namespace art { namespace engine {


// Reads the whole file into memory.
IMFILE *fopen(const char *fname)
{
    FILE *f = g_fopen(fname, "rb");

    if (!f) {
        return NULL;
    }

    IMFILE *mf = new IMFILE;
    memset(mf, 0, sizeof(*mf));
    fseek(f, 0, SEEK_END);
    mf->size = ftell(f);
    mf->data = new char[mf->size];
    fseek(f, 0, SEEK_SET);
    fread(mf->data, 1, mf->size, f);
    fclose(f);
    mf->pos = 0;
    mf->eof = false;

    return mf;
}

IMFILE *gfopen(const char *fname) { return fopen(fname); }

#ifndef WIN32
IMFILE *gfopen_mapped(const char *fname)
{
    int fd = ::g_open(fname, O_RDONLY);
    if (fd >= 0) {
        struct stat st;
        if (fstat(fd, &st) == 0 && st.st_size > 0) {
            void *data =
                mmap(nullptr, st.st_size, PROT_READ, MAP_PRIVATE, fd, 0);
            if (data != MAP_FAILED) {
                IMFILE *mf = new IMFILE;
                memset(mf, 0, sizeof(*mf));
                mf->fd = fd;
                mf->size = st.st_size;
                mf->data = static_cast<char *>(data);
                mf->mapped = true;
                return mf;
            }
        }
        close(fd);
    }
    
    // not mappable: read it as usual
    return gfopen(fname);
}
#else
IMFILE *gfopen_mapped(const char *fname) { return gfopen(fname); }
#endif

IMFILE *fopen(unsigned *buf, ssize_t size)
{

    IMFILE *mf = new IMFILE;
    memset(mf, 0, sizeof(*mf));
    mf->fd = -1;
    mf->size = size;
    mf->data = new char[mf->size];
    memcpy((void *)mf->data, buf, size);
    mf->pos = 0;
    mf->eof = false;
    return mf;
}

void fclose(IMFILE *f)
{
#ifndef WIN32
    if (f->mapped) {
        munmap(static_cast<void *>(f->data), f->size);
        close(f->fd);
        delete f;
        return;
    }
#endif
    delete[] f->data;
    delete f;
}

int fscanf(IMFILE *f, const char *s...)
{
    // fscanf not easily wrapped since we have no terminating \0 at end
    // of file data and vsscanf() won't tell us how many characters that
    // were parsed. However, only dcraw.cc code use it and only for "%f" and
    // "%d", so we make a dummy fscanf here just to support dcraw case.
    char buf[51], *endptr = nullptr;
    ssize_t copy_sz = f->size - f->pos;

    if (copy_sz >= static_cast<ssize_t>(sizeof(buf))) {
        copy_sz = sizeof(buf) - 1;
    }

    memcpy(buf, &f->data[f->pos], copy_sz);
    buf[copy_sz] = '\0';
    va_list ap;
    va_start(ap, s);

    if (strcmp(s, "%d") == 0) {
        int i = strtol(buf, &endptr, 10);

        if (endptr == buf) {
            va_end(ap);
            return 0;
        }

        int *pi = va_arg(ap, int *);
        *pi = i;
    } else if (strcmp(s, "%f") == 0) {
        float f = strtof(buf, &endptr);

        if (endptr == buf) {
            va_end(ap);
            return 0;
        }

        float *pf = va_arg(ap, float *);
        *pf = f;
    }

    va_end(ap);
    f->pos += endptr - buf;
    return 1;
}

char *fgets(char *s, ssize_t n, IMFILE *f)
{

    if (f->pos >= f->size) {
        f->eof = true;
        return nullptr;
    }

    ssize_t i = 0;

    do {
        s[i++] = f->data[f->pos++];
    } while (i < n && f->pos < f->size);

    return s;
}

void imfile_set_plistener(IMFILE *f, art::engine::ProgressListener *plistener,
                          double progress_range)
{
    f->plistener = plistener;
    f->progress_range = progress_range;
    f->progress_next = f->size / 10 + 1;
    f->progress_current = 0;
}

void imfile_update_progress(IMFILE *f)
{
    if (!f->plistener || f->progress_current < f->progress_next) {
        return;
    }

    do {
        f->progress_next += f->size / 10 + 1;
    } while (f->progress_next < f->progress_current);

    double p = (double)f->progress_current / f->size;

    if (p > 1.0) {
        /* this can happen if same bytes are read over and over again. Progress
           bar is not intended to be exact, just give some progress indication
           for normal raw file access patterns */
        p = 1.0;
    }

    f->plistener->setProgress(p * f->progress_range);
}


} } // namespace art::engine
