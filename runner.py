from brain_runtime import apply
from response_classification import classify

apply()

import runner_v84

runner_v84.classify = classify
main = runner_v84.main
score_allow_unknown = runner_v84.score_allow_unknown


if __name__ == "__main__":
    main()
