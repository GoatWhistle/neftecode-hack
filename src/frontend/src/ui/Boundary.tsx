import { Component } from "react";
import type { ErrorInfo, ReactNode } from "react";

export interface BoundaryProps {
  children: ReactNode;
}

interface BoundaryState {
  failed: boolean;
  message: string | null;
}

export class Boundary extends Component<BoundaryProps, BoundaryState> {
  constructor(props: BoundaryProps) {
    super(props);
    this.state = { failed: false, message: null };
  }

  static getDerivedStateFromError(error: unknown): BoundaryState {
    const message = error instanceof Error ? error.message : String(error);
    return { failed: true, message: message.slice(0, 300) };
  }

  override componentDidCatch(error: unknown, info: ErrorInfo): void {
    console.error("Интерфейс остановлен", error, info.componentStack);
  }

  override render(): ReactNode {
    if (!this.state.failed) return this.props.children;
    return (
      <div className="boundary" role="alert">
        <h1 className="boundary__title">Интерфейс остановлен</h1>
        <p className="boundary__lead">
          Экран не смог отрисоваться. Расчёт на сервере это не затрагивает: его результат
          останется в журнале прогона. Перезагрузите страницу, чтобы продолжить.
        </p>
        {this.state.message === null ? null : (
          <p className="boundary__reason">{this.state.message}</p>
        )}
        <button type="button" className="boundary__again" onClick={() => window.location.reload()}>
          Перезагрузить страницу
        </button>
      </div>
    );
  }
}
