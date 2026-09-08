import scraper
from pricing import prices as pt_prices

# A camada de aquisição usa um parser de preços PT/EU mais completo sem alterar o cérebro V8.
scraper.prices = pt_prices

from runner_v84 import main, score_allow_unknown


if __name__ == "__main__":
    main()
