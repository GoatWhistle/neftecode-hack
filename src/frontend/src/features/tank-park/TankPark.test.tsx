import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { TankParkTank, TankParkTrajectory } from "../../types";
import { TankPark } from "./TankPark";

const tank = (status: TankParkTank["status"], mass: number): TankParkTank => ({
  tank_id: "main-1", capacity_t: 4181.5, mass_t: mass,
  properties: { sulfur_mgkg: 8, t95_c: 352, cetane_number: 51.5, density_kgm3: 836.3 },
  status, batch_id: "batch-1", status_elapsed_h: 2, batch_age_h: 40,
  passport_duration_h: 12, passport_ready_in_h: 0, nominal_drain_h: 24,
  nominal_drain_tph: 174.229, provenance: "scenario", initial_uncertainty: []
});

const state = (status: TankParkTank["status"], mass: number) => ({
  model_version: "tank-park/1", elapsed_h: 0, initial_mass_t: 3000, mass_t: mass,
  total_in_t: 0, total_out_t: 3000 - mass, balance_error_t: 0, tanks: [tank(status, mass)]
});

const park: TankParkTrajectory = {
  model_version: "tank-park/1", feasible: true, reasons: [],
  frames: [
    { time_h: 0, inflow_t: 0, outflow_t: 0, inflow_by_tank: {}, outflow_by_tank: {},
      reasons: [], state: state("ready", 3000) },
    { time_h: 0.5, inflow_t: 0, outflow_t: 50, inflow_by_tank: {}, outflow_by_tank: { "main-1": 50 },
      reasons: [], state: state("draining", 2950) }
  ],
  terminal: state("draining", 2950)
};

describe("оборот резервуаров", () => {
  it("показывает серверные стадии, баланс и раскрывает источник", () => {
    render(<TankPark park={park} />);
    expect(screen.getByText("Оборот резервуаров")).toBeInTheDocument();
    expect(screen.getByText("баланс соблюдён")).toBeInTheDocument();
    expect(screen.getByText("готов")).toBeInTheDocument();
    expect(screen.getByText("слив")).toBeInTheDocument();
    fireEvent.click(screen.getByText("main-1"));
    expect(screen.getByText("Источник состояния")).toBeInTheDocument();
    expect(screen.getByText("scenario")).toBeInTheDocument();
    expect(screen.getAllByText(/выход 50/).length).toBeGreaterThan(0);
  });

  it("явно показывает первое ограничившее событие", () => {
    const failed = structuredClone(park);
    failed.feasible = false;
    failed.frames[1]!.reasons = ["готовые партии не покрывают спрос"];
    render(<TankPark park={failed} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/готовые партии не покрывают спрос/);
    expect(screen.getByText("есть ограничение")).toBeInTheDocument();
  });
});
