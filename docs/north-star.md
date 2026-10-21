# North star

Why Hatchery exists, what “good” looks like, and how free vs Enterprise fit the same brand.

This is product guidance for operators, contributors, and agents - not a feature backlog. Architecture how-to lives under [`architecture-nests.md`](architecture-nests.md). Open-core boundary: [ADR-0042](adr/0042-open-core-public-and-enterprise-tier.md).

<br>

## The bet

Hatchery is a **workhorse**, not a unicorn thesis.

Most teams do not need another fantastical platform. They need a **local-first, reliable, consistent builder** for interactive guest VMs: hatch from known media and Clutches, provision the same way every time, and operate Local or Remote Nests without renting a full cloud control plane for every lab.

The same class of problem keeps getting rebuilt inside organizations because cloud scale and headless CI never fully kick a solid on-prem / Nest-local builder out of the pipeline. When break-glass is still “use the defined device and config,” the need is still there.

<br>

## First-class siblings: effortless and repeatable

| Sibling | Means |
|---|---|
| **Effortless** | Form, Library, Clutch, and Nest paths that remove terminal friction for create, provision, and day-2 manage |
| **Repeatable** | The same Clutch + Software + answer-file definition hatches the same guest shape on Local or Remote capacity |

Neither is a later phase. UX without repeatability becomes tribal knowledge. Automation without ease of entry becomes another private toolkit only one person can run.

<br>

## What we optimize for

```
✅ Interactive guests (UI-as-user, packaging, desktop agents, installers)
✅ Cross-platform Controllers and Nest adapters (libvirt / UTM / Hyper-V × Local | Remote)
✅ Private / offline-friendly operation (license file, Nest Agent phones Controller only)
✅ Embeddable operator plane (CLI + shared orchestration; not browser-only)
✅ Clear free vs paid honesty (Local workhorse free; hierarchy paid)

❌ Pretending containers and headless e2e replace OS-session validation
❌ Forcing every lab onto costly full infrastructure stacks
❌ Hiding Enterprise value as secret prose while the brand stays mute
❌ Chasing venture-scale category theater over a durable craft product
```

Interactive OS fidelity matters when the product under test *is* the session. Headless runners win for API and service e2e; they lose for packaging, UI interaction, and “as a user” validation. Cross-platform Nest support (including Mac-hosted guests where the Nest allows it) is part of that wedge, not a side quest.

<br>

## Free edition vs Enterprise tier

One brand: **Hatchery**. Enterprise is a **purchase tier**, not a second product name.

| Edition | North-star job |
|---|---|
| **Free (MIT)** | A real product in a vacuum: Controller on Linux / macOS / Windows; one Local Nest when that provider works; portable Clutches and content between independent Controllers |
| **Enterprise** | Hierarchy at scale: Nest Agent, Remote Nest enroll/capacity, fleet Library / content origin, later SSO / RBAC / audit packs; Controller seat + Nest capacity entitlements |

Mid-flight hierarchy designs in history do not mean free “took away” a finished fleet suite. Free must stay useful alone. Paid must buy hierarchy and commercial trust that free does not pretend to include.

Commercial package and license portal live in the Enterprise tier repo; the **why** stays here so the brand and the business share one guiding light.

<br>

## Quiet success

Success is residual value from a beautiful workhorse: labs that hatch the same guest twice, operators who do not rebuild the toolkit every year, and teams that keep interactive Nest capacity in the pipeline without apologizing for it.

If an idea only counts when it is a one-in-a-million venture bet, most good tools die. Hatchery aims at the obvious need, done in a way that removes friction, respects architecture, and makes entry easy.

<br>

## Where this points next

| Surface | Role |
|---|---|
| This doc | Brand and product north star |
| [ADR-0042](adr/0042-open-core-public-and-enterprise-tier.md) | Locked free vs Enterprise boundary |
| [`architecture-nests.md`](architecture-nests.md) | Controller vs Nest planes |
| Hatchery-Enterprise | Commercial package, entitlements, license portal (points here for the why) |
