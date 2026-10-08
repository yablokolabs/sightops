import { NavLink } from "react-router-dom";

import { Logo } from "./Common";

const LINKS = [
  { to: "/home", label: "Home" },
  { to: "/industrial", label: "Industrial" },
  { to: "/inspections", label: "History" },
  { to: "/incidents", label: "Incidents" },
  { to: "/system", label: "System" }
];

export function Header() {
  return (
    <header className="sticky top-0 z-20 border-b border-navy-mid/40 bg-navy text-white shadow-lg">
      <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3">
        <NavLink to="/" className="flex items-center gap-3 rounded-lg focus-visible:ring-2 focus-visible:ring-brand-light">
          <Logo size={38} />
          <span className="leading-tight">
            <span className="block text-lg font-bold tracking-tight">SightOps</span>
            <span className="block text-[11px] uppercase tracking-[0.18em] text-brand-light">
              See. Diagnose. Act.
            </span>
          </span>
        </NavLink>

        <nav aria-label="Main" className="order-3 w-full sm:order-2 sm:w-auto">
          <ul className="flex flex-wrap items-center gap-1">
            {LINKS.map((link) => (
              <li key={link.to}>
                <NavLink
                  to={link.to}
                  className={({ isActive }) =>
                    [
                      "inline-flex min-h-[40px] items-center rounded-lg px-3 text-sm font-medium transition",
                      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-light",
                      isActive ? "bg-white/15 text-white" : "text-white/75 hover:bg-white/10 hover:text-white"
                    ].join(" ")
                  }
                >
                  {link.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>

        <p className="order-2 ml-auto hidden text-right text-[11px] leading-tight text-white/60 lg:block">
          An Agentic Visual Reliability Engineer
          <br />
          Yabloko Labs
        </p>
      </div>
    </header>
  );
}
