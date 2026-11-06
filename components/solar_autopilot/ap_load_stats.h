// House load statistics: 1-minute means over the last 3 h -> median (base load) and 5-min mean.
#pragma once

#include <array>
#include <cmath>
#include <cstdint>

namespace autopilot_core {

class LoadStats {
 public:
  static const uint16_t RING = 180;   // one-minute means = 3 h

  void add(float w) {
    acc_ += w;
    cnt_++;
  }
  // Close the current minute (call once a minute). base = max(median, floor).
  void minute(float floor_w);

  float median() const { return median_; }   // NAN until 30 min of data
  float mean5() const { return mean5_; }     // NAN until 5 min of data
  float base() const { return base_; }

 private:
  std::array<uint16_t, RING> ring_{};
  uint16_t n_ = 0, pos_ = 0, cnt_ = 0;
  float acc_ = 0;
  float median_ = NAN, mean5_ = NAN, base_ = 300;
};

}  // namespace autopilot_core
