import typer

app = typer.Typer(help="Workflow Builder agent UI prototype.")


@app.command()
def chat() -> None:
    """Launch the Textual TUI."""
    try:
        from agent.tui.app import WorkflowBuilderApp
    except ModuleNotFoundError as exc:
        missing = exc.name or "textual"
        typer.echo(
            f"Cannot launch the TUI because `{missing}` is not installed in the current Python environment.",
            err=True,
        )
        raise typer.Exit(code=1) from exc
    WorkflowBuilderApp().run()


@app.command()
def doctor() -> None:
    """Print a tiny runtime check for local dependencies."""
    try:
        import textual  # noqa: F401
    except ModuleNotFoundError:
        typer.echo("Textual is not installed in the current Python environment.")
        raise typer.Exit(code=1)
    try:
        import boto3  # noqa: F401
    except ModuleNotFoundError:
        typer.echo("Textual is available. boto3 is missing, so Bedrock conversation will fall back to local mode.")
        return
    typer.echo("Textual and boto3 are available.")
