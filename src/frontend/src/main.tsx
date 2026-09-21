import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { AgentPresentationMock } from "./mock/AgentPresentationMock";
import { ContributionHarness } from "./mock/ContributionHarness";
import "./styles/base.css";

const container = document.getElementById("root");

if (container) {
  const params = new URLSearchParams(window.location.search);
  const mock = params.get("mock");
  createRoot(container).render(
    <StrictMode>
      {mock === "f0405" ? <ContributionHarness />
        : mock === "review" || mock === "agents" ? <AgentPresentationMock />
        : <App />}
    </StrictMode>
  );
}
