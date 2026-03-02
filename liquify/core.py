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

    def command(self, *args: Any, **kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """
        Decorator to register a command with automatic dependency injection.
        Configurable objects in the signature are automatically loaded and flowed.
        """

        def decorator(f: Callable[..., Any]) -> Callable[..., Any]:
            import functools
            import inspect

            import confluid

            # 1. Inspect the function signature to find injectable parameters
            sig = inspect.signature(f)
            injectables = {}
            new_params = []

            for name, param in sig.parameters.items():
                # Check if the type hint is a configurable class
                annotation = param.annotation
                if hasattr(annotation, "__confluid_configurable__"):
                    injectables[name] = annotation
                else:
                    new_params.append(param)

            # 2. Create a wrapper function with a signature excluding injectables
            # This ensures Typer only sees the standard CLI arguments
            @functools.wraps(f)
            def wrapper(*f_args: Any, **f_kwargs: Any) -> Any:
                # Retrieve context from Typer (set in _global_callback)
                # Note: ctx is provided by Typer if requested, but we can also use self.context
                if not self.context:
                    return f(*f_args, **f_kwargs)

                # Resolve and inject configured objects
                for name, cls in injectables.items():
                    if name not in f_kwargs:
                        # Use the full config data as context for reference resolution
                        full_config = self.context.config_data if self.context else {}

                        # Reconstruct the object. confluid.load will:
                        # 1. Look for the class name in the config
                        # 2. Use the full context to resolve @references
                        instance = confluid.load(
                            {cls.__name__: full_config.get(cls.__name__, {})},
                            scopes=self.context.scopes if self.context else None,
                        )

                        f_kwargs[name] = instance

                return f(*f_args, **f_kwargs)

            # 3. Update the wrapper's signature so Typer doesn't see injectables
            wrapper.__signature__ = sig.replace(parameters=new_params)  # type: ignore

            # Register the wrapper with Typer
            return self.typer_app.command(*args, **kwargs)(wrapper)

        return decorator

    def run(self) -> Any:
        """Execute the Typer application."""
        return self.typer_app()
