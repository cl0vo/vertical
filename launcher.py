from __future__ import annotations

import sys


def main() -> None:
    from arara_factory.batch_worker import BatchRenderWorker

    if '--batch' in sys.argv:
        from arara_factory import batch_app as batch_module

        batch_module.BatchRenderWorker = BatchRenderWorker
        batch_module.main()
        return

    from arara_factory import app as app_module
    from arara_factory import integrated_batch as integrated_module

    integrated_module.BatchRenderWorker = BatchRenderWorker
    integrated_module.install(app_module)
    app_module.main()


if __name__ == '__main__':
    main()
