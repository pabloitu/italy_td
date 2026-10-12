"""Two additive fixes to floatCSEP's evaluation.py (c1bed2b), for the catalog-based L and MLL tests.

1. _TYPES: pseudolikelihood_test, MLL_magnitude_test and resampled_magnitude_test registered as
   "consistency". Without it a test with one of these funcs gets no tasks and is silently skipped.
2. Evaluation.compute: a test function that returns None (pyCSEP's pseudolikelihood_test on a window
   without observed events) is logged and skipped instead of crashing on result.to_dict().

Idempotent. Patches the installed package by default, or the file given as argument (repo copy).

usage: python scripts/patch_floatcsep_types.py [path/to/floatcsep/evaluation.py]
"""
import sys

if len(sys.argv) > 1:
    p = sys.argv[1]
else:
    import floatcsep.evaluation as ev
    p = ev.__file__
s = open(p).read()
done = []

new = ["pseudolikelihood_test", "MLL_magnitude_test", "resampled_magnitude_test"]
miss = [n for n in new if f'"{n}"' not in s]
if miss:
    add = "".join(f'\n        "{n}": "consistency",' for n in miss)
    s = s.replace('"number_test": "consistency",', '"number_test": "consistency",' + add, 1)
    done.append(f"types {miss}")

old = "        evaluation_result = self.func(*test_args, **self.func_kwargs)\n"
if old in s and "evaluation_result is None" not in s:
    s = s.replace(old, old + '''        if evaluation_result is None:
            log.info(f"[{self.name}] no result for {model.name} in {timewindow} (test not applicable)")
            return
''', 1)
    if "\nlog = logging.getLogger" not in s:
        s = s.replace("import datetime\n", "import datetime\nimport logging\n", 1)
        s = s.replace("from floatcsep.utils.helpers import parse_csep_func\n",
                      'from floatcsep.utils.helpers import parse_csep_func\n\nlog = logging.getLogger("floatLogger")\n', 1)
    done.append("None result skipped")

if done:
    open(p, "w").write(s)
    print(f"patched {p}: " + "; ".join(done))
else:
    print(f"already patched: {p}")
