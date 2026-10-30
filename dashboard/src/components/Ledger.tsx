import type { Step } from "../api";
import { money } from "../format";

export function Ledger({ steps }: Readonly<{ steps: Step[] }>) {
  return (
    <table className="ledger">
      <tbody>
        {steps.map((step, index) => (
          <tr key={`${step.label}-${String(index)}`}>
            <td>{step.label}</td>
            <td className="amount mono">{money(step.amount)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
