"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import {
  APP_NAME,
  SUBHEADLINE,
  PAID_CAPABILITIES,
  API_BASE,
  PROCESS_STEPS,
  CONSUMER_CASES,
  DECISION_MOMENTS,
  MEDIA,
} from "@/lib/config";
import styles from "./page.module.css";

function HomePageContent() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [prices, setPrices] = useState<Record<string, number>>({});
  const [evidenceServices, setEvidenceServices] = useState<
    { id: string; name: string; description?: string; capability?: string; priceMicro?: number }[]
  >([]);

  useEffect(() => {
    fetch(`${API_BASE}/api/investigate`)
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => {
        const nextPrices: Record<string, number> = {};
        for (const capability of data?.capabilities ?? []) {
          if (typeof capability.id === "string" && typeof capability.priceUsdc === "number") {
            nextPrices[capability.id] = capability.priceUsdc;
          }
        }
        setPrices(nextPrices);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetch(`${API_BASE}/api/providers`)
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => {
        if (Array.isArray(data?.services)) setEvidenceServices(data.services);
      })
      .catch(() => {});
  }, []);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (query.trim()) {
      router.push(`/investigate?q=${encodeURIComponent(query.trim())}`);
    } else {
      router.push("/investigate");
    }
  };

  const run = (q: string) =>
    router.push(`/investigate?q=${encodeURIComponent(q)}`);

  return (
    <div className={styles.main}>
      {/* HERO */}
      <section className={styles.heroSection}>
        <div className={`container ${styles.heroGrid}`}>
          <div className={styles.heroContent}>
            <p className={styles.eyebrow}>{APP_NAME} Â· Evidence-backed investigation</p>
            <h1 className={styles.heroTitle}>
              Investigate before you decide.
            </h1>
            <p className={styles.heroSub}>{SUBHEADLINE}</p>

            <form onSubmit={handleSearch} className={styles.searchBoxWrapper}>
              <label htmlFor="hero-q" className="sr-only">
                What are you unsure about?
              </label>
              <input
                id="hero-q"
                type="text"
                placeholder="Ask a claim, image, video, document, website, or data question"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className={styles.searchInput}
              />
              <button type="submit" className="btn btn-primary">
                Investigate â†’
              </button>
            </form>


          </div>

          <figure className={styles.heroVisual}>
            <img src={MEDIA.hero} alt={MEDIA.heroAlt} loading="eager" />
            <figcaption>
              Bring a claim, image, video, document, website, or data. Inquvia
              helps you understand what the evidence actually shows.
            </figcaption>
          </figure>
        </div>
      </section>

      {/* WHAT CAN YOU INVESTIGATE? */}
      <section id="capabilities" className={styles.toolsSection}>
        <div className="container">
          <div className="section-header">
            <span className="section-kicker">Capabilities</span>
            <h2 className="section-title">What can you investigate?</h2>
            <p className="section-lede">
              Investigate almost anything you&apos;re unsure about. Each type is
              an independent pay-per-request service.
            </p>
          </div>

          <div className={styles.toolsGrid}>
            {PAID_CAPABILITIES.map((cap) => (
              <button
                key={cap.id}
                type="button"
                className={styles.toolCard}
                onClick={() =>
                  router.push(
                    `/investigate/launch?capability=${encodeURIComponent(cap.id)}`
                  )
                }
              >
                <span className={styles.toolType}>{cap.inputTypes[0]}</span>
                <h3 className={styles.toolTitle}>{cap.title}</h3>
                <p className={styles.toolDesc}>{cap.description}</p>
                <div className={styles.toolMeta}>
                  <span className={styles.toolPrice}>
                    {prices[cap.id] === undefined
                      ? "Price at checkout"
                      : `$${prices[cap.id]} USDC`}
                  </span>
                  <span className={styles.toolGo}>Investigate â†’</span>
                </div>
              </button>
            ))}
          </div>
        </div>
      </section>

      {evidenceServices.length > 0 && (
        <section id="evidence" className={styles.toolsSection}>
          <div className="container">
            <div className="section-header">
              <span className="section-kicker">Evidence services</span>
              <h2 className="section-title">What Inquvia can check for you</h2>
              <p className="section-lede">
                Inquvia selects only the relevant evidence checks for your request,
                then shows the sources, limitations, and payment trail in your report.
              </p>
            </div>
            <div className={styles.toolsGrid}>
              {evidenceServices.map((service) => (
                <div key={service.id} className={styles.toolCard}>
                  <span className={styles.toolType}>{service.capability ?? "evidence"}</span>
                  <h3 className={styles.toolTitle}>{service.name}</h3>
                  <p className={styles.toolDesc}>{service.description || "Evidence analysis service"}</p>
                  <div className={styles.toolMeta}>
                    <span className={styles.toolPrice}>
                      {typeof service.priceMicro === "number"
                        ? `$${(service.priceMicro / 1_000_000).toFixed(3)} USDC`
                        : "Priced per request"}
                    </span>
                    <span className={styles.toolGo}>Selected when relevant</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>
      )}

      {/* REAL-LIFE QUESTIONS */}
      <section className={styles.casesSection}>
        <div className="container">
          <div className="section-header centered">
            <span className="section-kicker">Real situations</span>
            <h2 className="section-title">Things people check before they decide</h2>
            <p className="section-lede">
              Real questions ordinary people bring to Inquvia every day.
            </p>
          </div>
          <div className={styles.casesGrid}>
            {CONSUMER_CASES.map((c) => (
              <button
                key={c.title}
                type="button"
                className={styles.caseCard}
                onClick={() => run(c.question)}
              >
                <span className={styles.caseTitle}>{c.title}</span>
                <span className={styles.caseQuestion}>â€œ{c.question}â€</span>
              </button>
            ))}
          </div>
        </div>
      </section>

      {/* HOW IT WORKS */}
      <section id="process" className={styles.flowSection}>
        <div className="container">
          <div className="section-header">
            <span className="section-kicker">How it works</span>
            <h2 className="section-title">From â€œIâ€™m not sureâ€ to â€œI can decideâ€</h2>
            <p className="section-lede">
              No spreadsheets, no workflows. Just a question and an
              evidence-backed answer.
            </p>
          </div>
          <ol className={styles.flowGrid}>
            {PROCESS_STEPS.map((step) => (
              <li key={step.n} className={styles.flowCard}>
                <span className={styles.flowNumber}>{step.n}</span>
                <h3 className={styles.flowCardTitle}>{step.title}</h3>
                <p className={styles.flowCardText}>{step.detail}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* DECISION MOMENTS */}
      <section className={styles.decideSection}>
        <div className="container">
          <div className="section-header">
            <span className="section-kicker">Real-life decisions</span>
            <h2 className="section-title">
              Before you click. Before you buy. Before you believe.
            </h2>
          </div>
          <div className={styles.decideList}>
            {DECISION_MOMENTS.map((d) => (
              <div key={d.before} className={styles.decideRow}>
                <span className={styles.decideBefore}>{d.before}</span>
                <span className={styles.decideArrow}>â†’</span>
                <span className={styles.decideAction}>investigate</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* SUPPORTING IMAGES */}
      <section className={styles.photoBand}>
        <div className={`container ${styles.photoBandGrid}`}>
          <figure>
            <img src={MEDIA.shopping} alt={MEDIA.shoppingAlt} loading="lazy" />
            <figcaption>Is this seller legitimate?</figcaption>
          </figure>
          <figure>
            <img src={MEDIA.website} alt={MEDIA.websiteAlt} loading="lazy" />
            <figcaption>Can I trust this website?</figcaption>
          </figure>
          <figure>
            <img src={MEDIA.joboffer} alt={MEDIA.jobofferAlt} loading="lazy" />
            <figcaption>Is this job offer genuine?</figcaption>
          </figure>
          <figure>
            <img src={MEDIA.document} alt={MEDIA.documentAlt} loading="lazy" />
            <figcaption>Does this document look suspicious?</figcaption>
          </figure>
        </div>
      </section>

      {/* INVESTIGATION EXAMPLE */}
      <section id="evidence" className={styles.exampleSection}>
        <div className={`container ${styles.exampleGrid}`}>
          <div className={styles.exampleFlow}>
            <span className="section-kicker">Example</span>
            <h2 className="heading-xl">What does an assessment look like?</h2>
            <p className="text-muted">
              Question â†’ Investigation â†’ Evidence â†’ Cross-check â†’ Assessment. A
              product demonstration, not a testimonial.
            </p>
            <ol className={styles.exampleSteps}>
              <li>Question</li>
              <li>Investigation</li>
              <li>Evidence</li>
              <li>Cross-check</li>
              <li>Assessment</li>
            </ol>
          </div>

          <div className={styles.resultCard}>
            <p className={styles.resultQ}>â€œIs this online seller legitimate?â€</p>
            <div className={styles.resultVerdict}>
              <span className={styles.verdictBadge}>SUSPICIOUS</span>
              <span className={styles.verdictConfidence}>91% confidence</span>
            </div>
            <div className={styles.verdictBars}>
              <div className={styles.barRow}>
                <span>Supporting evidence</span>
                <div className={styles.barTrack}>
                  <div className={styles.barSupporting} />
                </div>
              </div>
              <div className={styles.barRow}>
                <span>Contradictory evidence</span>
                <div className={styles.barTrack}>
                  <div className={styles.barContradictory} />
                </div>
              </div>
              <div className={styles.barRow}>
                <span>Could not verify</span>
                <div className={styles.barTrack}>
                  <div className={styles.barUnknown} />
                </div>
              </div>
            </div>
            <p className={styles.resultNote}>
              Not every answer is true or false. Inconclusive. Some evidence
              conflicts. What we couldnâ€™t verify stays visible.
            </p>
            <Link href="/investigate" className="btn btn-primary">
              Start an Investigation â†’
            </Link>
          </div>
        </div>
      </section>

      {/* EVIDENCE-FIRST */}
      <section className={styles.evidenceSection}>
        <div className="container">
          <div className="section-header centered">
            <span className="section-kicker">Evidence first</span>
            <h2 className="section-title">Donâ€™t just get an answer. See why.</h2>
            <p className="section-lede">
              Every conclusion comes with the evidence behind it â€” what supports
              it, what contradicts it, and what remains unknown.
            </p>
          </div>
          <div className={styles.evidenceCols}>
            <div className={styles.evidenceCol}>
              <span className={styles.evidenceIcon}>ï¼‹</span>
              <h3>What supports the conclusion</h3>
              <p>Cited findings and sources back up the assessment.</p>
            </div>
            <div className={styles.evidenceCol}>
              <span className={styles.evidenceIcon}>âˆ’</span>
              <h3>What contradicts it</h3>
              <p>Conflicting signals are called out, not hidden.</p>
            </div>
            <div className={styles.evidenceCol}>
              <span className={styles.evidenceIcon}>?</span>
              <h3>What remains unknown</h3>
              <p>Gaps stay visible instead of being papered over.</p>
            </div>
          </div>
        </div>
      </section>

      {/* x402 */}
      <section id="x402" className={styles.x402Section}>
        <div className={`container ${styles.x402Grid}`}>
          <div className={styles.x402Flow}>
            <span>Investigation</span>
            <span className={styles.x402Step}>â†“</span>
            <span>x402</span>
            <span className={styles.x402Step}>â†“</span>
            <span>Algorand</span>
            <span className={styles.x402Step}>â†“</span>
            <span>USDC</span>
            <span className={styles.x402Step}>â†“</span>
            <span>Result</span>
          </div>
          <div>
            <span className="section-kicker">Pay per investigation</span>
            <h2 className="heading-xl">Pay only for the investigation you use.</h2>
            <p className="text-muted">
              Each investigation capability is a pay-per-request service.
              Payments use x402 with USDC on Algorand. You explore first â€” a
              wallet is only needed when a real payment is required, and you
              authorize each payment yourself in your Algorand wallet.
            </p>
            <div className={styles.walletSteps}>
              <span>Payment required</span>
              <span className={styles.x402Step}>â†“</span>
              <span>Connect Algorand wallet</span>
              <span className={styles.x402Step}>â†“</span>
              <span>Authorize</span>
              <span className={styles.x402Step}>â†“</span>
              <span>Continue</span>
            </div>
          </div>
        </div>
      </section>

      {/* FINAL CTA */}
      <section className={styles.ctaSection}>
        <div className="container">
          <div className={styles.ctaCard}>
            <div>
              <h2 className={styles.ctaCardTitle}>
                Something youâ€™re unsure about? Investigate it.
              </h2>
              <p className={styles.ctaCardSub}>
                Bring a claim, image, video, document, website, or data. See the
                evidence. Decide with more context.
              </p>
            </div>
            <div className={styles.ctaButtons}>
              <Link href="/investigate" className="btn btn-primary btn-lg">
                Start an Investigation â†’
              </Link>
              <a href="/#process" className="btn btn-secondary btn-lg">
                See How It Works
              </a>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}

const HomePage = dynamic(() => Promise.resolve(HomePageContent), {
  ssr: false,
});

export default HomePage;
