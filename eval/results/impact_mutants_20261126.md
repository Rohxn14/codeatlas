### polyglot_app

| selector | mutants | P | R | F1 | P@5 | R@5 | P@10 | R@10 | skipped | empty |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| engine | 22 | 0.8712 | 0.8636 | 0.8394 | 0.8333 | 0.8864 | 0.8333 | 0.8864 | 0.6364 | 0 |
| run-all | 22 | 0.3636 | 1.0 | 0.5212 | 0.3636 | 1.0 | 0.3636 | 1.0 | 0.0 | 0 |
| importing-tests | 22 | 0.7273 | 0.5909 | 0.6364 | 0.7273 | 0.5909 | 0.7273 | 0.5909 | 0.8068 | 5 |
| cochange-only | 22 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 1.0 | 22 |

4 test files. Caught by no test: 1; skipped: 1; not in the index: 0.

### itsdangerous

| selector | mutants | P | R | F1 | P@5 | R@5 | P@10 | R@10 | skipped | empty |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| engine | 29 | 0.908 | 0.819 | 0.8382 | 0.8161 | 0.819 | 0.8161 | 0.819 | 0.4552 | 0 |
| run-all | 29 | 0.5931 | 1.0 | 0.7237 | 0.5931 | 1.0 | 0.5931 | 1.0 | 0.0 | 0 |
| importing-tests | 29 | 0.908 | 0.596 | 0.6681 | 0.908 | 0.596 | 0.908 | 0.596 | 0.5931 | 0 |
| cochange-only | 29 | 0.6207 | 0.3276 | 0.4023 | 0.6207 | 0.3276 | 0.6207 | 0.3276 | 0.7379 | 4 |

5 test files. Caught by no test: 0; skipped: 1; not in the index: 0.

### Leave one benchmark out (natural cut-off)

| held out | cut-off tuned on the others | F1 there | shipped cut-off | F1 | best possible cut-off | F1 |
| --- | --- | --- | --- | --- | --- | --- |
| polyglot_app | 0.45 | 0.8182 | 0.3 | 0.8394 | 0.4 | 0.8485 |
| itsdangerous | 0.4 | 0.8382 | 0.3 | 0.8382 | 0.45 | 0.8391 |

