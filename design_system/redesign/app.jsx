// Mounts the redesign showcase: a design_canvas with two artboards
// (Direction A — Tightened, Direction B — Workbench) side-by-side, plus a
// shared Tweaks panel for switching tabs and tuning the canvas.

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "tab": "analysis",
  "accent": "indigo",
  "density": "regular",
  "typeSystem": "geist",
  "showAssistant": true
}/*EDITMODE-END*/;

// Apply tweaks to :root before rendering each artboard so both directions
// stay in sync. Accent map is intentionally narrow.
const ACCENTS = {
  indigo: { hue: 264, name: "Indigo (default)" },
  graphite: { hue: 250, name: "Graphite" },
  ember: { hue: 28, name: "Ember" },
  forest: { hue: 158, name: "Forest" },
};

function ApplyTokens({ tweaks }) {
  React.useEffect(() => {
    const root = document.documentElement;
    // tokens.css defines [data-accent="indigo|graphite|ember|forest"] and
    // [data-density="compact|regular|comfy"] variants.
    root.setAttribute("data-accent", tweaks.accent || "indigo");
    root.setAttribute("data-density", tweaks.density || "regular");
    root.setAttribute("data-type-system", tweaks.typeSystem || "inter");
  }, [tweaks.accent, tweaks.density, tweaks.typeSystem]);
  return null;
}

function App() {
  const [tweaks, setTweak] = useTweaks(TWEAK_DEFAULTS);
  // Single source of truth for the active step: tweaks.tab. No local mirror —
  // a local mirror was racing with the EDITMODE round-trip and leaving the
  // background artboard out of sync with the focus overlay.
  const tab = tweaks.tab || "analysis";
  const setTab = (t) => setTweak("tab", t);

  // Hide the floating assistant inside the artboards; the showcase has its own
  // chrome, and rendering two FABs at once is visual noise.
  const showAssistant = tweaks.showAssistant;

  return (
    <>
      <ApplyTokens tweaks={tweaks} />

      <DesignCanvas>
        <DCSection
          id="redesign"
          title="Workspace redesign"
          subtitle="Workbench direction for the four-step flow. Drag to pan · scroll to zoom · click the frame to focus it."
        >
          <DCArtboard id="b" label="Direction B · Workbench" width={1500} height={1100}>
            <DirectionB tab={tab} setTab={setTab} />
          </DCArtboard>
        </DCSection>
      </DesignCanvas>

      <TweaksPanel title="Showcase tweaks">
        <TweakSection label="View" />
        <TweakSelect
          label="Active step"
          value={tweaks.tab}
          options={[
            { value: "resume",   label: "01 · Resume" },
            { value: "jobs",     label: "02 · Job Search" },
            { value: "jd",       label: "03 · JD Review" },
            { value: "analysis", label: "04 · Analysis" },
          ]}
          onChange={(v) => setTweak("tab", v)}
        />
        <TweakToggle
          label="Show assistant FAB"
          value={tweaks.showAssistant}
          onChange={(v) => setTweak("showAssistant", v)}
        />

        <TweakSection label="Theme" />
        <TweakRadio
          label="Accent"
          value={tweaks.accent}
          options={Object.keys(ACCENTS)}
          onChange={(v) => setTweak("accent", v)}
        />
        <TweakRadio
          label="Density"
          value={tweaks.density}
          options={["compact", "regular", "comfy"]}
          onChange={(v) => setTweak("density", v)}
        />
        <TweakSection label="Type system" />
        <TweakRadio
          label="Family"
          value={tweaks.typeSystem}
          options={["inter", "geist", "editorial", "manrope", "original"]}
          onChange={(v) => setTweak("typeSystem", v)}
        />
      </TweaksPanel>
    </>
  );
}

// Hide assistant globally if tweak says so — done via CSS so it works inside
// both artboards without prop-drilling.
const styleEl = document.createElement("style");
styleEl.textContent = `
  body.no-fab .rd-fab { display: none !important; }
  body.no-fab .rd-assistant { display: none !important; }
`;
document.head.appendChild(styleEl);

// Reactive class toggle — re-read tweaks via the EDITMODE-merged JSON so we
// don't need to thread the prop through the artboard chain.
function applyFabVisibility() {
  const t = (window.__TWEAK_STATE__ || TWEAK_DEFAULTS);
  document.body.classList.toggle("no-fab", !t.showAssistant);
}
// Patch useTweaks calls to also publish state globally for the side-effect above.
const originalSet = window.useTweaks;
// not easy to patch cleanly — instead, observe via MutationObserver on body? Skip.
// Simplest: tap into postMessage round-trip.
window.addEventListener("message", (e) => {
  if (e.data && e.data.type === "__edit_mode_set_keys" && e.data.edits) {
    Object.assign(window.__TWEAK_STATE__ ||= { ...TWEAK_DEFAULTS }, e.data.edits);
    applyFabVisibility();
  }
});
window.__TWEAK_STATE__ = { ...TWEAK_DEFAULTS };
applyFabVisibility();

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
