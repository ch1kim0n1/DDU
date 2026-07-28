import {
  useEffect,
  useLayoutEffect,
  useRef,
  type DependencyList,
  type RefObject,
} from "react";

import {Flip, gsap, killContext, prefersReducedMotion, splitWords} from "./motion";

const useIsoLayoutEffect =
  typeof window !== "undefined" ? useLayoutEffect : useEffect;

export function useGsapContext(
  factory: (ctx: gsap.Context) => void,
  deps: DependencyList,
  scopeRef?: RefObject<HTMLElement | null>,
) {
  useIsoLayoutEffect(() => {
    if (prefersReducedMotion()) return;
    const ctx = gsap.context(() => {
      factory(ctx);
    }, scopeRef?.current ?? undefined);
    return () => killContext(ctx);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}

/** Masthead brand mark pulse + status beacon. */
export function useShellMotion(rootRef: RefObject<HTMLElement | null>) {
  useGsapContext(() => {
    const mark = rootRef.current?.querySelector(".brand-mark");
    const beacon = rootRef.current?.querySelector(".system-state i");
    if (mark) {
      gsap.fromTo(
        mark,
        {rotate: -8, scale: 0.85, opacity: 0},
        {rotate: 0, scale: 1, opacity: 1, duration: 0.7, ease: "dduSlam"},
      );
      gsap.to(mark, {
        y: -2,
        duration: 2.4,
        yoyo: true,
        repeat: -1,
        ease: "sine.inOut",
        delay: 0.8,
      });
    }
    if (beacon) {
      gsap.to(beacon, {
        boxShadow: "0 0 0 8px rgba(185, 245, 106, 0.08)",
        duration: 1.4,
        yoyo: true,
        repeat: -1,
        ease: "sine.inOut",
      });
    }
    gsap.from(".masthead .brand span:last-child, .system-state", {
      y: -12,
      opacity: 0,
      duration: 0.55,
      stagger: 0.08,
      ease: "dduReveal",
      delay: 0.15,
    });
  }, [], rootRef);
}

/** Home hero word reveal, create-card slam, registry scroll stagger + magnetic files. */
export function useHomeMotion(
  rootRef: RefObject<HTMLElement | null>,
  caseCount: number,
) {
  useGsapContext((ctx) => {
    const root = rootRef.current;
    if (!root) return;

    const title = root.querySelector<HTMLElement>(".hero h1");
    const eyebrow = root.querySelector(".hero .eyebrow");
    const lede = root.querySelector(".hero .lede");
    const card = root.querySelector(".create-card");

    const tl = gsap.timeline({defaults: {ease: "dduReveal"}});
    if (eyebrow) {
      tl.from(eyebrow, {y: 18, opacity: 0, duration: 0.45}, 0);
    }
    if (title) {
      const words = splitWords(title);
      gsap.set(words, {yPercent: 110, rotate: 4});
      tl.to(
        words,
        {
          yPercent: 0,
          rotate: 0,
          duration: 0.85,
          stagger: 0.055,
          ease: "dduSlam",
        },
        0.08,
      );
    }
    if (lede) {
      tl.from(lede, {y: 24, opacity: 0, duration: 0.55}, 0.35);
    }
    if (card) {
      tl.from(
        card,
        {
          x: 48,
          y: 36,
          opacity: 0,
          rotate: 1.5,
          duration: 0.75,
          ease: "dduSlam",
        },
        0.2,
      );
      // Scan-line sweep across the create card
      const scan = document.createElement("div");
      scan.className = "gsap-scan";
      card.appendChild(scan);
      gsap.fromTo(
        scan,
        {xPercent: -120, opacity: 0},
        {
          xPercent: 140,
          opacity: 0.7,
          duration: 1.1,
          ease: "power2.inOut",
          delay: 0.9,
        },
      );
    }

    const files = root.querySelectorAll(".case-file");
    if (files.length) {
      gsap.from(files, {
        scrollTrigger: {
          trigger: root.querySelector(".registry") || root,
          start: "top 78%",
        },
        y: 48,
        opacity: 0,
        rotateX: 12,
        transformPerspective: 800,
        duration: 0.7,
        stagger: {each: 0.08, from: "start"},
        ease: "dduSlam",
      });

      files.forEach((file) => {
        const el = file as HTMLElement;
        const onMove = (event: MouseEvent) => {
          const rect = el.getBoundingClientRect();
          const dx = event.clientX - (rect.left + rect.width / 2);
          const dy = event.clientY - (rect.top + rect.height / 2);
          gsap.to(el, {
            x: dx * 0.08,
            y: dy * 0.08,
            rotateY: dx * 0.03,
            rotateX: -dy * 0.03,
            duration: 0.35,
            ease: "power3.out",
            transformPerspective: 700,
          });
        };
        const onLeave = () => {
          gsap.to(el, {
            x: 0,
            y: 0,
            rotateX: 0,
            rotateY: 0,
            duration: 0.55,
            ease: "dduSnap",
          });
        };
        el.addEventListener("mousemove", onMove);
        el.addEventListener("mouseleave", onLeave);
        ctx.add(() => {
          el.removeEventListener("mousemove", onMove);
          el.removeEventListener("mouseleave", onLeave);
        });
      });
    }

    const heading = root.querySelector(".registry .section-heading");
    if (heading) {
      gsap.from(heading, {
        scrollTrigger: {
          trigger: heading,
          start: "top 85%",
        },
        y: 20,
        opacity: 0,
        duration: 0.5,
        ease: "dduReveal",
      });
    }
  }, [caseCount], rootRef);
}

/** Investigation case header, intake, metrics, and tab bar entrance. */
export function useCaseMotion(rootRef: RefObject<HTMLElement | null>, ready: boolean) {
  useGsapContext(() => {
    if (!ready) return;
    const root = rootRef.current;
    if (!root) return;

    const tl = gsap.timeline({defaults: {ease: "dduReveal"}});
    tl.from(".case-header", {y: 28, opacity: 0, duration: 0.55}, 0)
      .from(
        ".intake-grid > *",
        {y: 22, opacity: 0, duration: 0.45, stagger: 0.06},
        0.12,
      )
      .from(
        ".metric-strip .metric",
        {y: 18, opacity: 0, scale: 0.96, duration: 0.4, stagger: 0.05},
        0.22,
      )
      .from(".tab-bar", {y: 16, opacity: 0, duration: 0.4}, 0.28)
      .from(".tab-panel, .dashboard-grid", {y: 24, opacity: 0, duration: 0.5}, 0.34);

    // Subtle evidence ticker under busy actions
    const busy = root.querySelector(".upload-control.busy span");
    if (busy) {
      gsap.to(busy, {
        backgroundPosition: "200% 0",
        duration: 1.2,
        repeat: -1,
        ease: "none",
      });
    }
  }, [ready], rootRef);
}

/** Flip-based tab panel transition. */
export function useTabPanelMotion(
  panelRef: RefObject<HTMLElement | null>,
  tab: string,
) {
  const prevTab = useRef(tab);

  useIsoLayoutEffect(() => {
    if (prefersReducedMotion()) {
      prevTab.current = tab;
      return;
    }
    const panel = panelRef.current;
    if (!panel) {
      prevTab.current = tab;
      return;
    }

    if (prevTab.current === tab) {
      gsap.fromTo(
        panel,
        {opacity: 0, y: 18, filter: "blur(4px)"},
        {opacity: 1, y: 0, filter: "blur(0px)", duration: 0.45, ease: "dduReveal"},
      );
      return;
    }

    const state = Flip.getState(panel);
    prevTab.current = tab;
    gsap.fromTo(
      panel,
      {opacity: 0, y: 28, rotateX: 4, transformOrigin: "50% 0%"},
      {
        opacity: 1,
        y: 0,
        rotateX: 0,
        duration: 0.5,
        ease: "dduSlam",
        onComplete: () => {
          Flip.from(state, {
            duration: 0.35,
            ease: "power2.out",
            absolute: false,
            nested: true,
          });
        },
      },
    );
  }, [tab, panelRef]);
}

/** Animate metric numbers when value changes. */
export function useCountUp(
  elRef: RefObject<HTMLElement | null>,
  value: number,
) {
  const previous = useRef(0);

  useIsoLayoutEffect(() => {
    const el = elRef.current;
    if (!el) return;
    if (prefersReducedMotion()) {
      el.textContent = String(value);
      previous.current = value;
      return;
    }
    const proxy = {n: previous.current};
    gsap.to(proxy, {
      n: value,
      duration: 0.8,
      ease: "dduSnap",
      onUpdate: () => {
        el.textContent = String(Math.round(proxy.n)).padStart(2, "0");
      },
    });
    previous.current = value;
  }, [value]);
}

/** Pulse intel log when content updates. */
export function useIntelLogMotion(
  logRef: RefObject<HTMLElement | null>,
  content: string,
) {
  useIsoLayoutEffect(() => {
    if (!content || prefersReducedMotion()) return;
    const el = logRef.current;
    if (!el) return;
    gsap.fromTo(
      el,
      {opacity: 0.35, y: 10},
      {opacity: 1, y: 0, duration: 0.4, ease: "dduReveal"},
    );
    gsap.fromTo(
      el,
      {boxShadow: "inset 0 0 0 0 rgba(230, 88, 43, 0.45)"},
      {
        boxShadow: "inset 3px 0 0 0 rgba(230, 88, 43, 0.85)",
        duration: 0.35,
        yoyo: true,
        repeat: 1,
      },
    );
  }, [content]);
}
