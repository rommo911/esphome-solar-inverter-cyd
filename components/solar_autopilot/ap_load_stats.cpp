#include "ap_load_stats.h"

#include <algorithm>

namespace autopilot_core {

void LoadStats::minute(float floor_w) {
  if (cnt_ > 0) {   // no data = no sample
    ring_[pos_] = (uint16_t) std::min(65535.0f, std::max(0.0f, acc_ / cnt_));
    pos_ = (pos_ + 1) % RING;
    if (n_ < RING) n_++;
    acc_ = 0;
    cnt_ = 0;
  }
  if (n_ >= 30) {
    std::array<uint16_t, RING> v = ring_;
    std::nth_element(v.begin(), v.begin() + n_ / 2, v.begin() + n_);
    median_ = v[n_ / 2];
  }
  if (n_ >= 5) {
    float sum = 0;
    for (int i = 1; i <= 5; i++) sum += ring_[(pos_ + RING - i) % RING];
    mean5_ = sum / 5;
  }
  base_ = std::max(std::isnan(median_) ? 0.0f : median_, floor_w);
}

}  // namespace autopilot_core
