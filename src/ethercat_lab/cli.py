from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import typer
from IPython.terminal.embed import InteractiveShellEmbed
from traitlets.config import Config
from .master import Master
from .magics import EtherMagics, register_custom_formatters

app = typer.Typer(help="EtherCAT IPython REPL")


def _merge_module_namespace(module: object, user_ns: dict[str, object]) -> None:
    for name, value in vars(module).items():
        if name.startswith("_"):
            continue
        user_ns.setdefault(name, value)


def _load_custom_module(path: Path, *, bus: Master) -> tuple[str, object]:
    module_path = path.resolve()
    module_name = module_path.stem
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    setattr(module, "bus", bus)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module_name, module


@app.command()
def main(
    ifname: str = typer.Argument(..., help="EtherCAT interface"),
    macros: Path | None = typer.Option(
        None,
        "--macros",
        "-m",
        help="Path to a Python module with custom REPL macros/helpers",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
    ),
    merge_macros: bool = typer.Option(
        False,
        "--merge-macros-ns",
        "-M",
        help="Merge public names from the macros module into the REPL namespace",
    ),
):
    config = Config()
    config.InteractiveShell.colors = "lightbg"
    config.InteractiveShell.confirm_exit = False
    config.TerminalIPythonApp.display_banner = False
    config.InteractiveShellApp.extensions = ["autoreload"]
    config.InteractiveShell.ast_node_interactivity = "last_expr_or_assign"

    bus = Master(ifname)
    user_ns: dict[str, object] = {
        "bus": bus,
    }


    #estensione deve essere loaded dopo che i magic creano il bus!
    shell = InteractiveShellEmbed(config=config, user_ns=user_ns)
    shell.register_magics(EtherMagics(shell, bus))
    register_custom_formatters(shell)
    shell.extension_manager.load_extension("autoreload")
    shell.run_cell("%autoreload 2")
    shell.run_cell("%ec_slaves")
    if macros is not None:
        try:
            module_name, module = _load_custom_module(macros, bus=bus)
            user_ns[module_name] = module
            if merge_macros:
                _merge_module_namespace(module, user_ns)
            print(f"Loaded custom module '{module_name}' from {macros.resolve()}")
        except Exception as exc:
            print(f"Failed to load custom module: {exc}")

    shell()

if __name__ == "__main__":
    app()