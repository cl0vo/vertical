from __future__ import annotations

import sys


def main() -> None:
    if '--batch' in sys.argv:
        from arara_factory.batch_app import main as batch_main

        batch_main()
        return

    from arara_factory.app import main as single_main

    single_main()


if __name__ == '__main__':
    main()
