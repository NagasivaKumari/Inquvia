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
  MEDIA,
} from "@/lib/config";
import styles from "./page.module.css";

// Capability card thumbnail mapping matching reference aesthetics
const CAPABILITY_MEDIA: Record<string, { image: string; tag: string }> = {
  "claim-investigation": {
    image: "https://images.unsplash.com/photo-1455390582262-044cdead277a?auto=format&fit=crop&w=800&q=80",
    tag: "TEXT",
  },
  "image-investigation": {
    image: "https://images.unsplash.com/photo-1516035069371-29a1b244cc32?auto=format&fit=crop&w=800&q=80",
    tag: "IMAGE",
  },
  "video-investigation": {
    image: "https://images.unsplash.com/photo-1574717024653-61fd2cf4d44d?auto=format&fit=crop&w=800&q=80",
    tag: "VIDEO",
  },
  "document-investigation": {
    image: "/document-audit.jpg",
    tag: "DOCUMENT",
  },
  "source-investigation": {
    image: "https://images.unsplash.com/photo-1507238691740-187a5b1d37b8?auto=format&fit=crop&w=800&q=80",
    tag: "URL",
  },
  "data-investigation": {
    image: "/evidence-matrix.jpg",
    tag: "DATA",
  },
  "audio-investigation": {
    image: "https://images.unsplash.com/photo-1590602847861-f357a9332bbc?auto=format&fit=crop&w=800&q=80",
    tag: "AUDIO",
  },
};

// Real situation cards matching reference composition
const REAL_SITUATIONS = [
  {
    image: MEDIA.shopping,
    question: "Is this seller legitimate?",
  },
  {
    image: MEDIA.website,
    question: "Can I trust this website?",
  },
  {
    image: MEDIA.joboffer,
    question: "Is this job offer genuine?",
  },
  {
    image: MEDIA.document,
    question: "Does this document look suspicious?",
  },
];

// Interactive Assessment Demo Stages
const DEMO_STAGES = [
  {
    id: "question",
    label: "Question",
    badge: "SUBMITTED",
    badgeType: "neutral",
    confidence: "Initial intake",
    supporting: 0,
    contradictory: 0,
    unknown: 100,
    note: "User asks: “Is this online seller legitimate?” Inquvia formulates the scope of investigation.",
  },
  {
    id: "investigation",
    label: "Investigation",
    badge: "INSPECTING",
    badgeType: "info",
    confidence: "Sources dispatched",
    supporting: 35,
    contradictory: 20,
    unknown: 45,
    note: "Independent web, registry, domain provenance, and consumer report checks dispatched.",
  },
  {
    id: "evidence",
    label: "Evidence",
    badge: "ANALYZING",
    badgeType: "warning",
    confidence: "Findings mapped",
    supporting: 60,
    contradictory: 30,
    unknown: 25,
    note: "Signals collected: Domain registered 12 days ago, product photos stolen, missing SSL business profile.",
  },
  {
    id: "cross-check",
    label: "Cross-check",
    badge: "CORROBORATING",
    badgeType: "warning",
    confidence: "Signals weighed",
    supporting: 72,
    contradictory: 32,
    unknown: 18,
    note: "Contradiction checking: Registered address is a vacant lot; customer reviews copied from known scam lists.",
  },
  {
    id: "assessment",
    label: "Assessment",
    badge: "SUSPICIOUS",
    badgeType: "danger",
    confidence: "91% confidence",
    supporting: 78,
    contradictory: 32,
    unknown: 18,
    note: "Not every answer is true or false. Inconclusive. Some evidence conflicts. What we couldn’t verify stays visible.",
  },
];

function HomePageContent() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [prices, setPrices] = useState<Record<string, number>>({});
  const [evidenceServices, setEvidenceServices] = useState<
    { id: string; name: string; description?: string; capability?: string; priceMicro?: number }[]
  >([]);
  const [demoStageIndex, setDemoStageIndex] = useState(4); // Default: Assessment stage

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

  // Subtle scroll-reveal observer
  useEffect(() => {
    if (typeof window === "undefined" || !("IntersectionObserver" in window)) return;
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add(styles.sectionVisible);
          }
        });
      },
      { threshold: 0.08, rootMargin: "0px 0px -40px 0px" }
    );

    const elements = document.querySelectorAll(`.${styles.revealOnScroll}`);
    elements.forEach((el) => observer.observe(el));

    return () => observer.disconnect();
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

  // Display the 6 primary capabilities in the 3x2 grid shown in the reference
  const displayedCapabilities = PAID_CAPABILITIES.slice(0, 6);
  const currentStage = DEMO_STAGES[demoStageIndex];

  return (
    <div className={styles.main}>
      {/* HERO SECTION */}
      <section className={`${styles.heroSection} ${styles.revealOnScroll}`}>
        <div className={`container ${styles.heroGrid}`}>
          <div className={styles.heroContent}>
            <p className={styles.eyebrow}>
              INQUVIA // EVIDENCE-BACKED INVESTIGATION
            </p>
            <h1 className={styles.heroTitle}>
              Investigate before{" "}
              <span className={styles.heroTitleHighlight}>you decide.</span>
            </h1>
            <p className={styles.heroSub}>{SUBHEADLINE}</p>

            <form onSubmit={handleSearch} className={styles.searchBoxWrapper}>
              <label htmlFor="hero-q" className="sr-only">
                What are you unsure about?
              </label>
              <input
                id="hero-q"
                type="text"
                placeholder="Ask a claim, image, video, document, website, or data..."
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className={styles.searchInput}
              />
              <button type="submit" className={styles.searchBtn}>
                Investigate <span className={styles.btnArrow}>&rarr;</span>
              </button>
            </form>

            <div className={styles.heroBadges}>
              <div className={styles.heroBadgeItem}>
                <span className={styles.heroBadgeIcon}>✓</span>
                <span>$0.50 per investigation</span>
              </div>
              <div className={styles.heroBadgeItem}>
                <span className={styles.heroBadgeIcon}>⚡</span>
                <span>Powered by Algorand</span>
              </div>
              <div className={styles.heroBadgeItem}>
                <span className={styles.heroBadgeIcon}>🛡</span>
                <span>Evidence you can trust</span>
              </div>
            </div>
          </div>

          <div className={styles.heroVisualWrapper}>
            <div className={styles.heroImageCard}>
              <img
                src="/hero-workspace.jpg"
                alt="Investigators reviewing evidence and analysis in workspace"
                loading="eager"
              />
            </div>
            <div className={styles.heroFloatingCard}>
              <h4 className={styles.heroFloatingTitle}>From questions to proven facts.</h4>
              <ul className={styles.heroFloatingList}>
                <li className={styles.heroFloatingItem}>
                  <span className={styles.heroFloatingCheck}>✓</span>
                  <span>Real evidence</span>
                </li>
                <li className={styles.heroFloatingItem}>
                  <span className={styles.heroFloatingCheck}>✓</span>
                  <span>Independent sources</span>
                </li>
                <li className={styles.heroFloatingItem}>
                  <span className={styles.heroFloatingCheck}>✓</span>
                  <span>On-chain verification</span>
                </li>
              </ul>
            </div>
            <div className={styles.heroHandwritingNote}>
              Real evidence. A more informed world.
            </div>
          </div>
        </div>
      </section>

      {/* CAPABILITIES: WHAT CAN YOU INVESTIGATE? */}
      <section id="capabilities" className={`${styles.toolsSection} ${styles.revealOnScroll}`}>
        <div className="container">
          <div className={styles.sectionHeader}>
            <span className={styles.sectionKicker}>Capabilities</span>
            <h2 className={styles.sectionTitle}>What can you investigate?</h2>
            <p className={styles.sectionLede}>
              Investigate almost anything you&apos;re unsure about. Each type is
              an independent pay-per-request service.
            </p>
          </div>

          <div className={styles.toolsGrid}>
            {displayedCapabilities.map((cap) => {
              const meta = CAPABILITY_MEDIA[cap.id] ?? {
                image: "/document-audit.jpg",
                tag: cap.inputTypes[0]?.toUpperCase() ?? "INSPECT",
              };
              return (
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
                  <div className={styles.toolCardMedia}>
                    <img src={meta.image} alt={cap.title} loading="lazy" />
                  </div>
                  <div className={styles.toolCardBody}>
                    <span className={styles.toolType}>{meta.tag}</span>
                    <h3 className={styles.toolTitle}>{cap.title}</h3>
                    <p className={styles.toolDesc}>{cap.description}</p>
                    <div className={styles.toolMeta}>
                      <span className={styles.toolPrice}>
                        {prices[cap.id] === undefined
                          ? "Price at checkout"
                          : `$${prices[cap.id]} USDC`}
                      </span>
                      <span className={styles.toolGo}>
                        Investigate <span className={styles.btnArrow}>&rarr;</span>
                      </span>
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      </section>

      {/* DYNAMIC EVIDENCE SERVICES (IF REGISTERED BY PROVIDERS) */}
      {evidenceServices.length > 0 && (
        <section id="evidence-services" className={`${styles.toolsSection} ${styles.revealOnScroll}`}>
          <div className="container">
            <div className={styles.sectionHeader}>
              <span className={styles.sectionKicker}>Evidence services</span>
              <h2 className={styles.sectionTitle}>What Inquvia can check for you</h2>
              <p className={styles.sectionLede}>
                Inquvia selects only the relevant evidence checks for your request,
                then shows the sources, limitations, and payment trail in your report.
              </p>
            </div>
            <div className={styles.toolsGrid}>
              {evidenceServices.map((service) => (
                <div key={service.id} className={styles.toolCard}>
                  <div className={styles.toolCardBody}>
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
                </div>
              ))}
            </div>
          </div>
        </section>
      )}

      {/* REAL-WORLD SITUATIONS */}
      <section className={`${styles.casesSection} ${styles.revealOnScroll}`}>
        <div className="container">
          <div className={styles.sectionHeader}>
            <span className={styles.sectionKicker}>Real situations</span>
            <h2 className={styles.sectionTitle}>Things people check before they decide</h2>
            <p className={styles.sectionLede}>
              Real questions ordinary people bring to Inquvia every day.
            </p>
          </div>
          <div className={styles.casesGrid}>
            {REAL_SITUATIONS.map((c) => (
              <button
                key={c.question}
                type="button"
                className={styles.caseCard}
                onClick={() => run(c.question)}
              >
                <div className={styles.caseCardMedia}>
                  <img src={c.image} alt={c.question} loading="lazy" />
                </div>
                <div className={styles.caseCardBody}>
                  <span className={styles.caseQuestion}>{c.question}</span>
                </div>
              </button>
            ))}
          </div>
        </div>
      </section>

      {/* HOW IT WORKS (01 TO 05 PROGRESSION) */}
      <section id="process" className={`${styles.flowSection} ${styles.revealOnScroll}`}>
        <div className="container">
          <div className={styles.sectionHeader}>
            <span className={styles.sectionKicker}>How it works</span>
            <h2 className={styles.sectionTitle}>From a question to a clear answer.</h2>
            <p className={styles.sectionLede}>
              A simple process. Real evidence. Greater confidence.
            </p>
          </div>
          <ol className={styles.flowGrid}>
            {PROCESS_STEPS.map((step, idx) => (
              <li key={step.n} className={styles.flowCard}>
                <span className={styles.flowNumberBadge}>{step.n}</span>
                <h3 className={styles.flowCardTitle}>{step.title}</h3>
                <p className={styles.flowCardText}>{step.detail}</p>
                {idx < PROCESS_STEPS.length - 1 && (
                  <span className={styles.flowArrow} aria-hidden="true">&rarr;</span>
                )}
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* ASSESSMENT DEMONSTRATION EXAMPLE */}
      <section id="example" className={`${styles.exampleSection} ${styles.revealOnScroll}`}>
        <div className={`container ${styles.exampleGrid}`}>
          <div className={styles.exampleFlow}>
            <span className={styles.sectionKicker}>Example</span>
            <h2 className={styles.sectionTitle}>What does an assessment look like?</h2>
            <p className={styles.sectionLede}>
              Question &rarr; Investigation &rarr; Evidence &rarr; Cross-check &rarr; Assessment.
              A product demonstration, not a testimonial.
            </p>
            <ol className={styles.exampleSteps}>
              {DEMO_STAGES.map((stage, idx) => (
                <li key={stage.id}>
                  <button
                    type="button"
                    onClick={() => setDemoStageIndex(idx)}
                    className={`${styles.exampleStepBtn} ${demoStageIndex === idx ? styles.exampleStepActive : ""}`}
                    aria-pressed={demoStageIndex === idx}
                  >
                    <span>{stage.label}</span>
                    <span className={styles.stepIndicator}>{demoStageIndex === idx ? "●" : "○"}</span>
                  </button>
                </li>
              ))}
            </ol>
          </div>

          <div className={styles.resultCard}>
            <div className={styles.resultHeader}>
              <span className={`${styles.verdictBadge} ${styles[`verdict_${currentStage.badgeType}`]}`}>
                {currentStage.badge}
              </span>
              <span className={styles.verdictConfidence}>{currentStage.confidence}</span>
            </div>
            <div className={styles.verdictBars}>
              <div className={styles.barRow}>
                <span className={styles.barLabel}>Supporting evidence ({currentStage.supporting}%)</span>
                <div className={styles.barTrack}>
                  <div className={styles.barSupporting} style={{ width: `${currentStage.supporting}%` }} />
                </div>
              </div>
              <div className={styles.barRow}>
                <span className={styles.barLabel}>Contradictory evidence ({currentStage.contradictory}%)</span>
                <div className={styles.barTrack}>
                  <div className={styles.barContradictory} style={{ width: `${currentStage.contradictory}%` }} />
                </div>
              </div>
              <div className={styles.barRow}>
                <span className={styles.barLabel}>Could not verify ({currentStage.unknown}%)</span>
                <div className={styles.barTrack}>
                  <div className={styles.barUnknown} style={{ width: `${currentStage.unknown}%` }} />
                </div>
              </div>
            </div>
            <p className={styles.resultNote}>
              {currentStage.note}
            </p>
            <Link href="/investigate" className={styles.exampleCtaBtn}>
              See full example <span className={styles.btnArrow}>&rarr;</span>
            </Link>
          </div>
        </div>
      </section>

      {/* EVIDENCE-FIRST DIFFERENTIATOR */}
      <section id="evidence" className={`${styles.evidenceSection} ${styles.revealOnScroll}`}>
        <div className="container">
          <div className={`${styles.sectionHeader} ${styles.sectionHeaderCentered}`}>
            <span className={styles.sectionKicker}>Evidence first</span>
            <h2 className={styles.sectionTitle}>Don’t just get an answer. See why.</h2>
            <p className={styles.sectionLede}>
              Every conclusion comes with the evidence behind it — what supports
              it, what contradicts it, and what remains unknown.
            </p>
          </div>
          <div className={styles.evidenceCols}>
            <div className={styles.evidenceCol}>
              <span className={styles.evidenceIcon}>+</span>
              <h3>What supports the conclusion</h3>
              <p>Cited findings and sources back up the assessment.</p>
            </div>
            <div className={styles.evidenceCol}>
              <span className={styles.evidenceIcon}>&minus;</span>
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

      {/* RESTRAINED X402 / ALGORAND SECTION */}
      <section id="x402" className={`${styles.x402Section} ${styles.revealOnScroll}`}>
        <div className={`container ${styles.x402Grid}`}>
          <div className={styles.x402Flow}>
            <div className={styles.x402FlowStep}>
              <span>1. Submit Question</span>
            </div>
            <div className={styles.x402FlowStepArrow}>&darr;</div>
            <div className={styles.x402FlowStep}>
              <span>2. x402 Micropayment Request</span>
            </div>
            <div className={styles.x402FlowStepArrow}>&darr;</div>
            <div className={styles.x402FlowStep}>
              <span>3. Algorand On-Chain Settlement</span>
            </div>
            <div className={styles.x402FlowStepArrow}>&darr;</div>
            <div className={styles.x402FlowStep}>
              <span>4. Evidence Dossier Delivered</span>
            </div>
          </div>
          <div>
            <span className={styles.sectionKicker}>Pay per investigation</span>
            <h2 className={styles.sectionTitle}>Pay only for the investigation you use.</h2>
            <p className={styles.sectionLede}>
              Each investigation capability is an independent pay-per-request service.
              Payments use x402 with USDC on Algorand. You explore first — a
              wallet is only needed when a real payment is required, and you
              authorize each payment yourself in your Algorand wallet.
            </p>
            <div className={styles.walletSteps}>
              <span className={styles.walletStepBadge}>Payment required</span>
              <span>&rarr;</span>
              <span className={styles.walletStepBadge}>Connect Algorand wallet</span>
              <span>&rarr;</span>
              <span className={styles.walletStepBadge}>Authorize</span>
              <span>&rarr;</span>
              <span className={styles.walletStepBadge}>Verified dossier</span>
            </div>
          </div>
        </div>
      </section>

      {/* FINAL CTA */}
      <section className={`${styles.ctaSection} ${styles.revealOnScroll}`}>
        <div className="container">
          <div className={styles.ctaCard}>
            <div>
              <span className={styles.sectionKicker} style={{ color: "var(--color-orange)" }}>
                READY TO INVESTIGATE?
              </span>
              <h2 className={styles.ctaCardTitle}>
                Turn your questions into verified answers.
              </h2>
              <p className={styles.ctaCardSub}>
                Evidence-backed. AI-powered. On-chain.
              </p>
            </div>
            <div className={styles.ctaButtons}>
              <Link href="/investigate" className={styles.ctaPrimaryBtn}>
                Start an investigation <span className={styles.btnArrow}>&rarr;</span>
              </Link>
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
