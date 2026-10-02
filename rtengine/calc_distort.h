#pragma once

namespace art { namespace engine {

int calcDistortion(unsigned char *img1, unsigned char *img2, int ncols,
                   int nrows, int nfactor, double &distortion);

} } // namespace art::engine
