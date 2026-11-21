"""Ask from the command line: python -m scripts.ask "dialysis" "Sitamarhi" [more "service|place" pairs...]"""
import sys
import time

from carematch.recommend import CareIndex, recommend
from carematch.render import to_text


def main():
    args = sys.argv[1:]
    pairs = [tuple(a.split('|', 1)) for a in args if '|' in a] or [(args[0], args[1])]
    t = time.time()
    index = CareIndex.from_csv()
    print(f'(index built in {time.time() - t:.1f}s)\n')
    for service, place in pairs:
        print('=' * 100)
        print(to_text(recommend(index, service, place)))
        print()


if __name__ == '__main__':
    main()
