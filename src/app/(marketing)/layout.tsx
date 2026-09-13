import { PublicNav } from "@/components/marketing/PublicNav";
import { Footer } from "@/components/marketing/Footer";
import "@/styles/marketing.css";

export default function MarketingLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="mkt">
      <PublicNav />
      <main>{children}</main>
      <Footer />
    </div>
  );
}
