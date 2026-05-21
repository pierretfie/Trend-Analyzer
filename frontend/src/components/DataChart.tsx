import {
  BarChart,
  Bar,
  LineChart,
  Line,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
} from "recharts";

type ChartProps = {
  code: string;
};

const COLORS = [
  "#2ee6a8",
  "#818cf8",
  "#60a5fa",
  "#f59e0b",
  "#f43f5e",
  "#10b981",
];

function toNumberOrNull(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value !== "string") return null;
  const cleaned = value.replace(/,/g, "").replace(/%/g, "").trim();
  if (!cleaned) return null;
  const n = Number(cleaned);
  return Number.isFinite(n) ? n : null;
}

export function DataChart({ code }: ChartProps) {
  let parsed: any;
  try {
    parsed = JSON.parse(code);
  } catch (err) {
    return (
      <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 text-xs text-amber-500 font-mono">
        Invalid chart JSON
        <pre className="mt-2 text-slate-300 opacity-70 whitespace-pre-wrap">
          {code}
        </pre>
      </div>
    );
  }

  const { type, data, xKey, yKey, series } = parsed;

  if (!data || !Array.isArray(data)) {
    return (
      <div className="rounded-xl border border-danger/30 bg-danger/10 p-4 text-xs text-danger font-mono">
        Chart JSON missing "data" array.
      </div>
    );
  }

  const objectRows = data.filter((row: any) => row && typeof row === "object");
  const firstRow = objectRows[0] ?? {};
  const allKeys = Array.from(
    new Set(objectRows.flatMap((row: any) => Object.keys(row))),
  );
  const candidateX =
    typeof xKey === "string" && xKey in firstRow
      ? xKey
      : (["x", "year", "date", "month", "label", "name"].find((k) =>
          allKeys.includes(k),
        ) ?? "name");
  const candidateY =
    typeof yKey === "string" && allKeys.includes(yKey)
      ? yKey
      : (allKeys.find((k) => {
          if (k === candidateX) return false;
          return objectRows.some(
            (row: any) => toNumberOrNull(row?.[k]) !== null,
          );
        }) ?? "value");

  const normalizedData = data.map((row: any) => {
    if (!row || typeof row !== "object") return row;
    const next = { ...row };
    for (const key of Object.keys(next)) {
      const num = toNumberOrNull(next[key]);
      if (num !== null) next[key] = num;
    }
    return next;
  });

  const normalizedSeries = Array.isArray(series)
    ? series.filter(
        (s: any) =>
          s && typeof s.dataKey === "string" && allKeys.includes(s.dataKey),
      )
    : null;
  const hasValidSeries = !!(normalizedSeries && normalizedSeries.length > 0);

  const hasPlottableValues = hasValidSeries
    ? normalizedData.some((row: any) =>
        normalizedSeries.some(
          (s: any) =>
            typeof row?.[s.dataKey] === "number" &&
            Number.isFinite(row[s.dataKey]),
        ),
      )
    : normalizedData.some(
        (row: any) =>
          typeof row?.[candidateY] === "number" &&
          Number.isFinite(row[candidateY]),
      );

  if (!hasPlottableValues) {
    return (
      <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 text-xs text-amber-400 font-mono">
        Chart has no plottable numeric values. Check `yKey`/`series.dataKey` and
        numeric formatting.
      </div>
    );
  }

  const renderChart = () => {
    switch (type) {
      case "bar":
        return (
          <BarChart
            data={normalizedData}
            margin={{ top: 10, right: 30, left: 0, bottom: 0 }}
          >
            <CartesianGrid
              strokeDasharray="3 3"
              stroke="rgba(255,255,255,0.1)"
            />
            <XAxis
              dataKey={candidateX}
              stroke="#94a3b8"
              fontSize={12}
              tickLine={false}
            />
            <YAxis
              stroke="#94a3b8"
              fontSize={12}
              tickLine={false}
              axisLine={false}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "#0f172a",
                borderColor: "rgba(255,255,255,0.1)",
                borderRadius: "8px",
              }}
              itemStyle={{ color: "#e2e8f0" }}
            />
            {hasValidSeries && normalizedSeries.length > 1 && (
              <Legend wrapperStyle={{ fontSize: "12px" }} />
            )}
            {hasValidSeries ? (
              normalizedSeries.map((s: any, i: number) => (
                <Bar
                  key={s.dataKey}
                  dataKey={s.dataKey}
                  name={s.name || s.dataKey}
                  fill={s.fill || COLORS[i % COLORS.length]}
                  radius={[4, 4, 0, 0]}
                />
              ))
            ) : (
              <Bar
                dataKey={candidateY}
                fill={COLORS[0]}
                radius={[4, 4, 0, 0]}
              />
            )}
          </BarChart>
        );
      case "line":
        return (
          <LineChart
            data={normalizedData}
            margin={{ top: 10, right: 30, left: 0, bottom: 0 }}
          >
            <CartesianGrid
              strokeDasharray="3 3"
              stroke="rgba(255,255,255,0.1)"
            />
            <XAxis
              dataKey={candidateX}
              stroke="#94a3b8"
              fontSize={12}
              tickLine={false}
            />
            <YAxis
              stroke="#94a3b8"
              fontSize={12}
              tickLine={false}
              axisLine={false}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "#0f172a",
                borderColor: "rgba(255,255,255,0.1)",
                borderRadius: "8px",
              }}
              itemStyle={{ color: "#e2e8f0" }}
            />
            {hasValidSeries && normalizedSeries.length > 1 && (
              <Legend wrapperStyle={{ fontSize: "12px" }} />
            )}
            {hasValidSeries ? (
              normalizedSeries.map((s: any, i: number) => (
                <Line
                  key={s.dataKey}
                  type="monotone"
                  dataKey={s.dataKey}
                  name={s.name || s.dataKey}
                  stroke={s.stroke || COLORS[i % COLORS.length]}
                  strokeWidth={2}
                  dot={{ r: 4, fill: "#0f172a", strokeWidth: 2 }}
                  activeDot={{ r: 6 }}
                />
              ))
            ) : (
              <Line
                type="monotone"
                dataKey={candidateY}
                stroke={COLORS[0]}
                strokeWidth={2}
                dot={{ r: 4, fill: "#0f172a", strokeWidth: 2 }}
                activeDot={{ r: 6 }}
              />
            )}
          </LineChart>
        );
      case "area":
        return (
          <AreaChart
            data={normalizedData}
            margin={{ top: 10, right: 30, left: 0, bottom: 0 }}
          >
            <CartesianGrid
              strokeDasharray="3 3"
              stroke="rgba(255,255,255,0.1)"
            />
            <XAxis
              dataKey={candidateX}
              stroke="#94a3b8"
              fontSize={12}
              tickLine={false}
            />
            <YAxis
              stroke="#94a3b8"
              fontSize={12}
              tickLine={false}
              axisLine={false}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "#0f172a",
                borderColor: "rgba(255,255,255,0.1)",
                borderRadius: "8px",
              }}
              itemStyle={{ color: "#e2e8f0" }}
            />
            {hasValidSeries && normalizedSeries.length > 1 && (
              <Legend wrapperStyle={{ fontSize: "12px" }} />
            )}
            {hasValidSeries ? (
              normalizedSeries.map((s: any, i: number) => (
                <Area
                  key={s.dataKey}
                  type="monotone"
                  dataKey={s.dataKey}
                  name={s.name || s.dataKey}
                  stroke={s.stroke || COLORS[i % COLORS.length]}
                  fill={s.fill || COLORS[i % COLORS.length]}
                  fillOpacity={0.3}
                  strokeWidth={2}
                />
              ))
            ) : (
              <Area
                type="monotone"
                dataKey={candidateY}
                stroke={COLORS[0]}
                fill={COLORS[0]}
                fillOpacity={0.3}
                strokeWidth={2}
              />
            )}
          </AreaChart>
        );
      case "pie":
        return (
          <PieChart margin={{ top: 0, right: 0, left: 0, bottom: 0 }}>
            <Tooltip
              contentStyle={{
                backgroundColor: "#0f172a",
                borderColor: "rgba(255,255,255,0.1)",
                borderRadius: "8px",
              }}
              itemStyle={{ color: "#e2e8f0" }}
            />
            <Legend wrapperStyle={{ fontSize: "12px" }} />
            <Pie
              data={normalizedData}
              dataKey={candidateY}
              nameKey={candidateX}
              cx="50%"
              cy="50%"
              outerRadius={80}
              label={({ name, percent }) =>
                `${name} ${(((percent ?? 0) as number) * 100).toFixed(0)}%`
              }
              labelLine={false}
              stroke="rgba(0,0,0,0.2)"
            >
              {normalizedData.map((_: any, index: number) => (
                <Cell
                  key={`cell-${index}`}
                  fill={COLORS[index % COLORS.length]}
                />
              ))}
            </Pie>
          </PieChart>
        );
      case "doughnut":
        return (
          <PieChart margin={{ top: 0, right: 0, left: 0, bottom: 0 }}>
            <Tooltip
              contentStyle={{
                backgroundColor: "#0f172a",
                borderColor: "rgba(255,255,255,0.1)",
                borderRadius: "8px",
              }}
              itemStyle={{ color: "#e2e8f0" }}
            />
            <Legend wrapperStyle={{ fontSize: "12px" }} />
            <Pie
              data={normalizedData}
              dataKey={candidateY}
              nameKey={candidateX}
              cx="50%"
              cy="50%"
              innerRadius={50}
              outerRadius={80}
              label={({ name, percent }) =>
                `${name} ${(((percent ?? 0) as number) * 100).toFixed(0)}%`
              }
              labelLine={false}
              stroke="rgba(0,0,0,0.2)"
            >
              {normalizedData.map((_: any, index: number) => (
                <Cell
                  key={`cell-${index}`}
                  fill={COLORS[index % COLORS.length]}
                />
              ))}
            </Pie>
          </PieChart>
        );
      default:
        return (
          <div className="flex h-full items-center justify-center text-slate-500 text-sm">
            Unsupported chart type: {type}
          </div>
        );
    }
  };

  return (
    <div className="my-4 rounded-xl border border-white/[0.08] bg-surface-900/50 p-4">
      {parsed.title && (
        <h4 className="text-center text-sm font-semibold text-slate-200 mb-4">
          {parsed.title}
        </h4>
      )}
      <div className="h-64 w-full">
        <ResponsiveContainer width="100%" height="100%">
          {renderChart()}
        </ResponsiveContainer>
      </div>
    </div>
  );
}
