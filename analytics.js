(function () {
  "use strict";

  const CONSENT_KEY = "tt-analytics-consent";
  const MEASUREMENT_ID = document
    .querySelector('meta[name="google-analytics-id"]')
    ?.getAttribute("content")
    ?.trim();

  let analyticsLoaded = false;
  const observedMilestones = new Set();

  function hasValidMeasurementId() {
    return /^G-[A-Z0-9]+$/i.test(MEASUREMENT_ID || "");
  }

  function track(eventName, parameters = {}) {
    if (!analyticsLoaded || typeof window.gtag !== "function") return;

    window.gtag("event", eventName, {
      ...parameters,
      transport_type: "beacon",
    });
  }

  function loadAnalytics() {
    if (analyticsLoaded || !hasValidMeasurementId()) return;

    window.dataLayer = window.dataLayer || [];
    window.gtag = function () {
      window.dataLayer.push(arguments);
    };

    window.gtag("js", new Date());
    window.gtag("config", MEASUREMENT_ID, {
      allow_google_signals: false,
      allow_ad_personalization_signals: false,
      cookie_flags: "SameSite=Lax;Secure",
    });

    const script = document.createElement("script");
    script.async = true;
    script.src = `https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(MEASUREMENT_ID)}`;
    document.head.append(script);
    analyticsLoaded = true;
  }

  function removeAnalyticsCookies() {
    document.cookie.split(";").forEach((cookie) => {
      const name = cookie.split("=")[0].trim();
      if (name === "_ga" || name.startsWith("_ga_")) {
        document.cookie = `${name}=; Max-Age=0; path=/; SameSite=Lax`;
        document.cookie = `${name}=; Max-Age=0; path=/; domain=.${location.hostname}; SameSite=Lax`;
      }
    });
  }

  function setConsent(choice) {
    localStorage.setItem(CONSENT_KEY, choice);
    document.getElementById("analytics-consent")?.remove();

    if (choice === "granted") {
      loadAnalytics();
    } else {
      removeAnalyticsCookies();
      if (typeof window.gtag === "function") {
        window.gtag("consent", "update", {
          analytics_storage: "denied",
          ad_storage: "denied",
          ad_user_data: "denied",
          ad_personalization: "denied",
        });
      }
    }
  }

  function showConsentPreferences() {
    document.getElementById("analytics-consent")?.remove();

    const panel = document.createElement("section");
    panel.id = "analytics-consent";
    panel.className = "analytics-consent";
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-labelledby", "analytics-consent-title");
    panel.innerHTML = `
      <div class="analytics-consent__copy">
        <h2 id="analytics-consent-title">Help us improve this website</h2>
        <p>With your permission, anonymous usage statistics help us understand which pages and store information are most useful. We do not use analytics for advertising.</p>
        <a href="privacy.html">Privacy details</a>
      </div>
      <div class="analytics-consent__actions">
        <button class="analytics-consent__decline" type="button" data-consent="denied">No thanks</button>
        <button class="analytics-consent__accept" type="button" data-consent="granted">Allow analytics</button>
      </div>
    `;

    panel.addEventListener("click", (event) => {
      const button = event.target.closest("[data-consent]");
      if (button) setConsent(button.dataset.consent);
    });

    document.body.append(panel);
    panel.querySelector("[data-consent='granted']")?.focus();
  }

  function installEventTracking() {
    document.addEventListener("click", (event) => {
      const link = event.target.closest("a[href]");
      if (!link) return;

      const href = link.getAttribute("href") || "";
      const label = (link.textContent || link.getAttribute("aria-label") || "").trim().replace(/\s+/g, " ").slice(0, 100);

      if (href.startsWith("tel:")) {
        track("contact_click", { contact_method: "phone", link_text: label });
      } else if (href.startsWith("mailto:")) {
        track("contact_click", { contact_method: "email", link_text: label });
      } else if (/weekly-ad\.pdf(?:$|[?#])/i.test(href)) {
        track("weekly_ad_open", { link_text: label });
      } else if (/facebook\.com|instagram\.com/i.test(href)) {
        const platform = /facebook\.com/i.test(href) ? "facebook" : "instagram";
        track("social_click", { platform, link_text: label });
      } else if (href.startsWith("#") && href.length > 1) {
        track("section_navigation", { section_id: href.slice(1), link_text: label });
      }
    });

    document.querySelectorAll("[data-analytics-preferences]").forEach((button) => {
      button.addEventListener("click", showConsentPreferences);
    });

    const milestones = [25, 50, 75, 90];
    let scrollTicking = false;
    window.addEventListener("scroll", () => {
      if (scrollTicking) return;
      scrollTicking = true;
      window.requestAnimationFrame(() => {
        const available = document.documentElement.scrollHeight - window.innerHeight;
        const percent = available > 0 ? Math.round((window.scrollY / available) * 100) : 100;
        milestones.forEach((milestone) => {
          if (percent >= milestone && !observedMilestones.has(milestone)) {
            observedMilestones.add(milestone);
            track("scroll_depth", { percent_scrolled: milestone });
          }
        });
        scrollTicking = false;
      });
    }, { passive: true });

    if ("IntersectionObserver" in window) {
      const observer = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          const eventName = entry.target.dataset.analyticsView;
          if (eventName) track(eventName);
          observer.unobserve(entry.target);
        });
      }, { threshold: 0.5 });

      document.querySelectorAll("[data-analytics-view]").forEach((element) => observer.observe(element));
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    installEventTracking();
    const consent = localStorage.getItem(CONSENT_KEY);

    if (consent === "granted") {
      loadAnalytics();
    } else if (consent !== "denied") {
      showConsentPreferences();
    }
  });
})();
