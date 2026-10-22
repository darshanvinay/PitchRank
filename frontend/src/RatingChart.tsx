import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { TeamDetail } from "./types";
const date = (value: string) =>
  new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short" }).format(
    new Date(`${value.slice(0, 10)}T12:00:00`),
  );
const number = new Intl.NumberFormat(undefined, {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});
export default function RatingChart({
  history,
}: {
  history: TeamDetail["history"];
}) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart
        data={history}
        margin={{ top: 16, right: 16, bottom: 0, left: 0 }}
        accessibilityLayer
      >
        <CartesianGrid vertical={false} stroke="var(--border)" />
        <XAxis
          dataKey="date"
          tickFormatter={date}
          minTickGap={65}
          tickLine={false}
          axisLine={false}
          tick={{ fontSize: 12, fill: "var(--muted)" }}
        />
        <YAxis
          domain={["auto", "auto"]}
          tickCount={4}
          tickLine={false}
          axisLine={false}
          tick={{ fontSize: 12, fill: "var(--muted)" }}
          width={48}
        />
        <Tooltip
          labelFormatter={(value) => date(String(value))}
          formatter={(value) => [number.format(Number(value)), "Elo rating"]}
          contentStyle={{
            background: "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: 6,
            color: "var(--text)",
          }}
        />
        <Line
          dataKey="rating"
          type="linear"
          stroke="var(--chart)"
          strokeWidth={2.5}
          dot={false}
          activeDot={{ r: 4 }}
          isAnimationActive={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
