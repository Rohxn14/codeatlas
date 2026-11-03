cmake_minimum_required(VERSION 3.10)
project(shapes C)
add_executable(app src/main.c src/util/log.c lib/geometry.c)
target_include_directories(app PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/lib/api)
