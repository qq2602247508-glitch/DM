import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useToast } from "../hooks/toastContext";
import { ToastProvider } from "./ToastProvider";

function Trigger() {
  const { showToast } = useToast();
  return <button onClick={() => showToast("战役已保存")}>触发</button>;
}

describe("ToastProvider", () => {
  it("shows user-visible mutation feedback", () => {
    render(<ToastProvider><Trigger /></ToastProvider>);
    fireEvent.click(screen.getByRole("button", { name: "触发" }));
    expect(screen.getByRole("status")).toHaveTextContent("战役已保存");
  });
});
