import Content from "./content";

export function generateStaticParams() {
  // Static export needs at least one param to emit the [id] route. Arbitrary
  // IDs are served by FastAPI's SPA fallback (index.html) and read from the
  // URL client-side, so a single placeholder is enough.
  return [{ id: "placeholder" }];
}

export default function ReportDetailPage() {
  return <Content />;
}