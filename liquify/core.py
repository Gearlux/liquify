from pathlib import Path
from typing import Any, Callable, List, Optional

import confluid
import logflow
import typer
from rich.console import Console

from liquify.context import LiquifyContext

# Shared rich console for beautiful CLI output
console = Console()


class LiquifyApp:
    """The main entry point for a Liquify-based application."""

    def __init__(self, name: str, **kwargs: Any) -> None:
        self.name = name
        self.typer_app = typer.Typer(name=name, **kwargs)
        self.context: Optional[LiquifyContext] = None

        # Define the global callback for common options
        self.typer_app.callback()(self._global_callback)

    def _global_callback(
        self,
        ctx: typer.Context,
        config: Optional[Path] = typer.Option(
            None, "--config", "-c", help="Path to the configuration YAML file.", show_default=False
        ),
        scope: List[str] = typer.Option(
            [], "--scope", "-s", help="Configuration scopes to activate.", show_default=False
        ),
        debug: bool = typer.Option(False, "--debug", "-d", help="Enable ultra-detailed debugging output."),
    ) -> None:
        """Global callback to initialize the Liquify context and bootstrap trio."""
        # 1. Initialize Context
        self.context = LiquifyContext(name=self.name, config_path=config, scopes=scope, debug=debug)

        # 2. Bootstrap Trio (Logging & Config)
        self._bootstrap()

        # 3. Store in Typer's internal context
        ctx.obj = self.context

    def _bootstrap(self) -> None:
        """Initialize LogFlow and Confluid based on CLI options."""
        if not self.context:
            return

        # A. Setup Logging (LogFlow)
        log_level = "DEBUG" if self.context.debug else "INFO"
        logflow.configure_logging(console_level=log_level)
        self.context.logger = logflow.get_logger(self.name)

        # B. Setup Configuration (Confluid)
        if self.context.config_path:
            if not self.context.config_path.exists():
                console.print(f"[bold red]Error:[/bold red] Configuration file not found: {self.context.config_path}")
                raise typer.Exit(code=1)

            try:
                # Load config with scopes
                self.context.config_data = confluid.load(self.context.config_path, scopes=self.context.scopes)
                if self.context.logger:
                    self.context.logger.debug(f"Configuration loaded from {self.context.config_path}")
            except Exception as e:
                # Log to console since logger might not be fully ready or error is critical
                console.print(f"[bold red]Error loading configuration:[/bold red] {e}")
                # Re-raise as typer.Exit to ensure CLI stops
                raise typer.Exit(code=1) from e

    def command(self, *args: Any, **kwargs: Any) -> Callable[[Any], Any]:
        """Decorator to register a command with the application."""
        return self.typer_app.command(*args, **kwargs)

    def run(self) -> Any:
        """Execute the Typer application."""
        return self.typer_app()
