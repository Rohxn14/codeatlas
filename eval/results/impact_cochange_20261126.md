click: indexed at 831c8f0948af519e45b90801d7430ff25451f972^; 108 of 410 queries name a file the index lacks
click (file in index): indexed at 831c8f0948af519e45b90801d7430ff25451f972^; 0 of 302 queries name a file the index lacks
cobra: indexed at 3c8a19ecd384dc4229545bb174310a50c493f4ae^; 57 of 322 queries name a file the index lacks
cobra (file in index): indexed at 3c8a19ecd384dc4229545bb174310a50c493f4ae^; 0 of 265 queries name a file the index lacks
express: indexed at 9e3dbb43744620b8b490c61c9269a168e0c0e3ae^; 31 of 290 queries name a file the index lacks
express (file in index): indexed at 9e3dbb43744620b8b490c61c9269a168e0c0e3ae^; 0 of 259 queries name a file the index lacks
# Co-change benchmark, 20261126

| repo | predictor | language | queries | precision@5 | recall@5 | precision@10 | recall@10 | no_prediction_share |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| click | cochange | all | 410 | 0.273 | 0.251 | 0.212 | 0.321 | 0.251 |
| click | cochange | markdown | 94 | 0.351 | 0.143 | 0.332 | 0.204 | 0.425 |
| click | cochange | python | 260 | 0.278 | 0.277 | 0.199 | 0.341 | 0.231 |
| click | cochange | rst | 32 | 0.131 | 0.212 | 0.106 | 0.359 | 0.000 |
| click | cochange | text | 2 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| click | cochange | toml | 15 | 0.133 | 0.551 | 0.100 | 0.675 | 0.000 |
| click | cochange | yaml | 7 | 0.738 | 0.343 | 0.637 | 0.343 | 0.429 |
| click | same-folder | all | 410 | 0.116 | 0.141 | 0.100 | 0.189 | 0.068 |
| click | same-folder | markdown | 94 | 0.049 | 0.096 | 0.043 | 0.143 | 0.000 |
| click | same-folder | python | 260 | 0.124 | 0.088 | 0.107 | 0.147 | 0.108 |
| click | same-folder | rst | 32 | 0.056 | 0.238 | 0.040 | 0.238 | 0.000 |
| click | same-folder | text | 2 | 0.100 | 0.250 | 0.071 | 0.250 | 0.000 |
| click | same-folder | toml | 15 | 0.187 | 0.768 | 0.133 | 0.768 | 0.000 |
| click | same-folder | yaml | 7 | 0.857 | 0.857 | 0.857 | 0.857 | 0.000 |
| click | impact | all | 410 | 0.194 | 0.169 | 0.162 | 0.216 | 0.339 |
| click | impact | markdown | 94 | 0.493 | 0.048 | 0.486 | 0.050 | 0.798 |
| click | impact | python | 260 | 0.171 | 0.185 | 0.130 | 0.250 | 0.235 |
| click | impact | rst | 32 | 0.131 | 0.212 | 0.130 | 0.263 | 0.000 |
| click | impact | text | 2 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| click | impact | toml | 15 | 0.120 | 0.484 | 0.097 | 0.541 | 0.000 |
| click | impact | yaml | 7 | 0.775 | 0.343 | 0.775 | 0.343 | 0.429 |
| click (file in index) | cochange | all | 302 | 0.271 | 0.309 | 0.204 | 0.387 | 0.106 |
| click (file in index) | cochange | markdown | 48 | 0.546 | 0.114 | 0.510 | 0.122 | 0.604 |
| click (file in index) | cochange | python | 200 | 0.271 | 0.353 | 0.191 | 0.436 | 0.010 |
| click (file in index) | cochange | rst | 32 | 0.131 | 0.212 | 0.106 | 0.359 | 0.000 |
| click (file in index) | cochange | text | 2 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| click (file in index) | cochange | toml | 15 | 0.133 | 0.551 | 0.100 | 0.675 | 0.000 |
| click (file in index) | cochange | yaml | 5 | 0.738 | 0.480 | 0.637 | 0.480 | 0.200 |
| click (file in index) | same-folder | all | 302 | 0.130 | 0.166 | 0.114 | 0.229 | 0.000 |
| click (file in index) | same-folder | markdown | 48 | 0.071 | 0.096 | 0.067 | 0.190 | 0.000 |
| click (file in index) | same-folder | python | 200 | 0.130 | 0.104 | 0.115 | 0.177 | 0.000 |
| click (file in index) | same-folder | rst | 32 | 0.056 | 0.238 | 0.040 | 0.238 | 0.000 |
| click (file in index) | same-folder | text | 2 | 0.100 | 0.250 | 0.071 | 0.250 | 0.000 |
| click (file in index) | same-folder | toml | 15 | 0.187 | 0.768 | 0.133 | 0.768 | 0.000 |
| click (file in index) | same-folder | yaml | 5 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |
| click (file in index) | impact | all | 302 | 0.194 | 0.229 | 0.162 | 0.294 | 0.103 |
| click (file in index) | impact | markdown | 48 | 0.493 | 0.095 | 0.486 | 0.098 | 0.604 |
| click (file in index) | impact | python | 200 | 0.171 | 0.241 | 0.130 | 0.326 | 0.005 |
| click (file in index) | impact | rst | 32 | 0.131 | 0.212 | 0.130 | 0.263 | 0.000 |
| click (file in index) | impact | text | 2 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| click (file in index) | impact | toml | 15 | 0.120 | 0.484 | 0.097 | 0.541 | 0.000 |
| click (file in index) | impact | yaml | 5 | 0.775 | 0.480 | 0.775 | 0.480 | 0.200 |
| cobra | cochange | all | 322 | 0.297 | 0.347 | 0.271 | 0.425 | 0.236 |
| cobra | cochange | go | 221 | 0.295 | 0.439 | 0.264 | 0.540 | 0.090 |
| cobra | cochange | make | 4 | 1.000 | 0.125 | 1.000 | 0.125 | 0.750 |
| cobra | cochange | markdown | 67 | 0.286 | 0.114 | 0.283 | 0.133 | 0.522 |
| cobra | cochange | text | 13 | 0.527 | 0.308 | 0.492 | 0.333 | 0.615 |
| cobra | cochange | yaml | 17 | 0.157 | 0.149 | 0.171 | 0.231 | 0.588 |
| cobra | same-folder | all | 322 | 0.192 | 0.316 | 0.159 | 0.465 | 0.043 |
| cobra | same-folder | go | 221 | 0.200 | 0.371 | 0.154 | 0.539 | 0.000 |
| cobra | same-folder | make | 4 | 0.100 | 0.100 | 0.075 | 0.225 | 0.000 |
| cobra | same-folder | markdown | 67 | 0.128 | 0.146 | 0.126 | 0.265 | 0.194 |
| cobra | same-folder | text | 13 | 0.239 | 0.297 | 0.247 | 0.390 | 0.077 |
| cobra | same-folder | yaml | 17 | 0.271 | 0.326 | 0.277 | 0.416 | 0.000 |
| cobra | impact | all | 322 | 0.229 | 0.278 | 0.220 | 0.393 | 0.264 |
| cobra | impact | go | 221 | 0.219 | 0.358 | 0.210 | 0.519 | 0.100 |
| cobra | impact | make | 4 | n/a | 0.000 | n/a | 0.000 | 1.000 |
| cobra | impact | markdown | 67 | 0.263 | 0.075 | 0.263 | 0.075 | 0.582 |
| cobra | impact | text | 13 | 0.527 | 0.308 | 0.492 | 0.333 | 0.615 |
| cobra | impact | yaml | 17 | 0.120 | 0.090 | 0.120 | 0.143 | 0.706 |
| cobra (file in index) | cochange | all | 265 | 0.292 | 0.403 | 0.263 | 0.497 | 0.121 |
| cobra (file in index) | cochange | go | 203 | 0.291 | 0.465 | 0.259 | 0.572 | 0.044 |
| cobra (file in index) | cochange | make | 4 | 1.000 | 0.125 | 1.000 | 0.125 | 0.750 |
| cobra (file in index) | cochange | markdown | 36 | 0.255 | 0.179 | 0.252 | 0.214 | 0.222 |
| cobra (file in index) | cochange | text | 12 | 0.527 | 0.333 | 0.492 | 0.361 | 0.583 |
| cobra (file in index) | cochange | yaml | 10 | 0.120 | 0.153 | 0.140 | 0.293 | 0.500 |
| cobra (file in index) | same-folder | all | 265 | 0.183 | 0.346 | 0.148 | 0.520 | 0.000 |
| cobra (file in index) | same-folder | go | 203 | 0.191 | 0.381 | 0.145 | 0.554 | 0.000 |
| cobra (file in index) | same-folder | make | 4 | 0.100 | 0.100 | 0.075 | 0.225 | 0.000 |
| cobra (file in index) | same-folder | markdown | 36 | 0.106 | 0.182 | 0.103 | 0.397 | 0.000 |
| cobra (file in index) | same-folder | text | 12 | 0.239 | 0.322 | 0.247 | 0.422 | 0.000 |
| cobra (file in index) | same-folder | yaml | 10 | 0.260 | 0.353 | 0.270 | 0.507 | 0.000 |
| cobra (file in index) | impact | all | 265 | 0.229 | 0.338 | 0.220 | 0.477 | 0.106 |
| cobra (file in index) | impact | go | 203 | 0.219 | 0.390 | 0.210 | 0.565 | 0.020 |
| cobra (file in index) | impact | make | 4 | n/a | 0.000 | n/a | 0.000 | 1.000 |
| cobra (file in index) | impact | markdown | 36 | 0.263 | 0.139 | 0.263 | 0.139 | 0.222 |
| cobra (file in index) | impact | text | 12 | 0.527 | 0.333 | 0.492 | 0.361 | 0.583 |
| cobra (file in index) | impact | yaml | 10 | 0.120 | 0.153 | 0.120 | 0.243 | 0.500 |
| express | cochange | all | 290 | 0.434 | 0.640 | 0.398 | 0.685 | 0.072 |
| express | cochange | javascript | 108 | 0.406 | 0.376 | 0.361 | 0.460 | 0.065 |
| express | cochange | json | 26 | 0.215 | 0.811 | 0.112 | 0.849 | 0.000 |
| express | cochange | markdown | 38 | 0.212 | 0.671 | 0.141 | 0.750 | 0.105 |
| express | cochange | text | 2 | n/a | 0.000 | n/a | 0.000 | 1.000 |
| express | cochange | yaml | 116 | 0.582 | 0.848 | 0.582 | 0.848 | 0.069 |
| express | same-folder | all | 290 | 0.332 | 0.569 | 0.318 | 0.606 | 0.014 |
| express | same-folder | javascript | 108 | 0.202 | 0.119 | 0.201 | 0.199 | 0.037 |
| express | same-folder | json | 26 | 0.169 | 0.734 | 0.086 | 0.734 | 0.000 |
| express | same-folder | markdown | 38 | 0.116 | 0.502 | 0.067 | 0.546 | 0.000 |
| express | same-folder | text | 2 | 0.000 | 0.000 | 0.050 | 0.167 | 0.000 |
| express | same-folder | yaml | 116 | 0.562 | 0.983 | 0.562 | 0.983 | 0.000 |
| express | impact | all | 290 | 0.462 | 0.411 | 0.465 | 0.474 | 0.169 |
| express | impact | javascript | 108 | 0.331 | 0.260 | 0.337 | 0.427 | 0.065 |
| express | impact | json | 26 | 0.846 | 0.734 | 0.846 | 0.734 | 0.000 |
| express | impact | markdown | 38 | 0.456 | 0.608 | 0.456 | 0.608 | 0.105 |
| express | impact | text | 2 | n/a | 0.000 | n/a | 0.000 | 1.000 |
| express | impact | yaml | 116 | 0.506 | 0.422 | 0.506 | 0.422 | 0.310 |
| express (file in index) | cochange | all | 259 | 0.406 | 0.626 | 0.366 | 0.677 | 0.058 |
| express (file in index) | cochange | javascript | 107 | 0.406 | 0.379 | 0.361 | 0.464 | 0.056 |
| express (file in index) | cochange | json | 26 | 0.215 | 0.811 | 0.112 | 0.849 | 0.000 |
| express (file in index) | cochange | markdown | 37 | 0.212 | 0.690 | 0.141 | 0.770 | 0.081 |
| express (file in index) | cochange | text | 1 | n/a | 0.000 | n/a | 0.000 | 1.000 |
| express (file in index) | cochange | yaml | 88 | 0.544 | 0.852 | 0.544 | 0.852 | 0.057 |
| express (file in index) | same-folder | all | 259 | 0.309 | 0.525 | 0.293 | 0.566 | 0.015 |
| express (file in index) | same-folder | javascript | 107 | 0.204 | 0.120 | 0.202 | 0.200 | 0.037 |
| express (file in index) | same-folder | json | 26 | 0.169 | 0.734 | 0.086 | 0.734 | 0.000 |
| express (file in index) | same-folder | markdown | 37 | 0.114 | 0.489 | 0.066 | 0.534 | 0.000 |
| express (file in index) | same-folder | text | 1 | 0.000 | 0.000 | 0.100 | 0.333 | 0.000 |
| express (file in index) | same-folder | yaml | 88 | 0.560 | 0.977 | 0.560 | 0.977 | 0.000 |
| express (file in index) | impact | all | 259 | 0.462 | 0.461 | 0.465 | 0.530 | 0.070 |
| express (file in index) | impact | javascript | 107 | 0.331 | 0.262 | 0.337 | 0.431 | 0.056 |
| express (file in index) | impact | json | 26 | 0.846 | 0.734 | 0.846 | 0.734 | 0.000 |
| express (file in index) | impact | markdown | 37 | 0.456 | 0.625 | 0.456 | 0.625 | 0.081 |
| express (file in index) | impact | text | 1 | n/a | 0.000 | n/a | 0.000 | 1.000 |
| express (file in index) | impact | yaml | 88 | 0.506 | 0.557 | 0.506 | 0.557 | 0.091 |

