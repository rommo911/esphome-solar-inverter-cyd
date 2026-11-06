# ESP-IDF component: the controller core only (the ESPHome glue, solar_autopilot.*, is not built).
# Use it with EXTRA_COMPONENT_DIRS pointing at this folder's parent, then REQUIRES solar_autopilot.
file(GLOB AP_SRCS "${CMAKE_CURRENT_LIST_DIR}/ap_*.cpp")
idf_component_register(SRCS ${AP_SRCS} INCLUDE_DIRS ".")
