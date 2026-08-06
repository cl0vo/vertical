from __future__ import annotations

import sys


def main() -> None:
    if '--batch' in sys.argv:
        from arara_factory.batch_app import main as batch_main

        batch_main()
        return

    from arara_factory import app as app_module
    from arara_factory.integrated_batch import install

    install(app_module)
    app_module.main()


if __name__ == '__main__':
    main()
