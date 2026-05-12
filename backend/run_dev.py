import importlib.util
import os
from pathlib import Path


def _env_flag(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {'1', 'true', 'yes', 'on'}


def load_flask_app_factory():
    module_path = Path(__file__).with_name('app.py')
    spec = importlib.util.spec_from_file_location('legacy_flask_app', module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'Could not load Flask app module from {module_path}')

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.create_app


if __name__ == '__main__':
    create_app = load_flask_app_factory()
    debug_enabled = _env_flag('APP_DEBUG', False)
    create_app().run(
        host='0.0.0.0',
        port=int(os.environ.get('PORT', '8080')),
        debug=debug_enabled,
        use_reloader=debug_enabled,
        threaded=True,
    )
