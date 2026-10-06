(() => {
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const data = window.CHART;
  const symbol = { EUR: "€", USD: "$", RSD: "дин." }[window.CURRENCY] || window.CURRENCY;
  const fmt = (v) => `${v.toLocaleString("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${symbol}`;

  Chart.defaults.font.family = css("--font");
  Chart.defaults.color = css("--muted");

  const scales = () => ({
    x: { grid: { display: false }, border: { color: css("--axis") }, ticks: { maxRotation: 0, autoSkipPadding: 12 } },
    y: { beginAtZero: true, grid: { color: css("--grid") }, border: { display: false },
         ticks: { callback: (v) => v.toLocaleString("ru-RU") } },
  });
  const tooltip = {
    backgroundColor: css("--surface"), titleColor: css("--ink"), bodyColor: css("--ink-2"),
    borderColor: css("--border"), borderWidth: 1, padding: 10,
    callbacks: {
      title: (items) => `${items[0].label} число`,
      label: (ctx) => `${ctx.dataset.label}: ${fmt(ctx.parsed.y)}`,
    },
  };
  const base = {
    responsive: true, maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    plugins: { legend: { display: false }, tooltip },
  };

  new Chart(document.getElementById("pace"), {
    type: "line",
    data: {
      labels: data.labels,
      datasets: [
        { label: "Потрачено", data: data.cumulative, borderColor: css("--series-1"), borderWidth: 2,
          pointRadius: 0, pointHoverRadius: 5, tension: 0 },
        { label: "План", data: data.ideal, borderColor: css("--muted"), borderWidth: 1.5, borderDash: [4, 3],
          pointRadius: 0, pointHoverRadius: 0 },
      ],
    },
    options: { ...base, scales: scales() },
  });

  new Chart(document.getElementById("daily"), {
    data: {
      labels: data.labels.slice(0, data.daily_spent.length),
      datasets: [
        { type: "line", label: "Лимит", data: data.daily_limit, borderColor: css("--muted"), borderWidth: 2,
          stepped: "middle", pointRadius: 0, pointHoverRadius: 0, order: 0 },
        { type: "bar", label: "Потрачено", data: data.daily_spent,
          backgroundColor: data.daily_spent.map((v, i) => v > data.daily_limit[i] ? css("--critical") : css("--series-1")),
          borderRadius: { topLeft: 4, topRight: 4 }, borderSkipped: "bottom", maxBarThickness: 18, order: 1 },
      ],
    },
    options: { ...base, scales: scales() },
  });
})();
