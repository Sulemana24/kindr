// ── DATA ──
const campaigns = [
  {
    id: 1,
    title: "Clean Water for Koforidua Communities",
    category: "community",
    categoryLabel: "Community",
    image:
      "https://images.unsplash.com/photo-1541544537156-7627a7a4aa1c?w=600&q=80",
    description:
      "Help us build 3 boreholes and water purification systems for 2,000 families in rural Ghana who currently walk 5km for safe water.",
    raised: 18450,
    target: 25000,
    donors: [
      { initials: "KA", color: "#7c3fc8" },
      { initials: "MS", color: "#185FA5" },
      { initials: "PO", color: "#D85A30" },
      { initials: "LN", color: "#1D9E75" },
    ],
    recentDonor: "Kwame A.",
    recentAmount: "Ghc150",
  },
  {
    id: 2,
    title: "Scholarships for Girls in STEM",
    category: "education",
    categoryLabel: "Education",
    image:
      "https://images.unsplash.com/photo-1509062522246-3755977927d7?w=600&q=80",
    description:
      "Fund full university scholarships for 10 brilliant young women from low-income families to pursue careers in science and technology.",
    raised: 41200,
    target: 50000,
    donors: [
      { initials: "AO", color: "#7c3fc8" },
      { initials: "TE", color: "#D85A30" },
      { initials: "RB", color: "#185FA5" },
    ],
    recentDonor: "Ama O.",
    recentAmount: "Ghc500",
  },
  {
    id: 3,
    title: "Reforestation: Plant 10,000 Trees",
    category: "environment",
    categoryLabel: "Environment",
    image:
      "https://images.unsplash.com/photo-1448375240586-882707db888b?w=600&q=80",
    description:
      "Join our mission to restore degraded forest land across 200 hectares. Each dollar plants a tree and fights climate change locally.",
    raised: 8700,
    target: 20000,
    donors: [
      { initials: "JM", color: "#3B6D11" },
      { initials: "CL", color: "#7c3fc8" },
      { initials: "FO", color: "#BA7517" },
      { initials: "HK", color: "#993556" },
    ],
    recentDonor: "James M.",
    recentAmount: "Ghc75",
  },
  {
    id: 4,
    title: "Mobile Medical Clinic for Remote Villages",
    category: "health",
    categoryLabel: "Health & Medical",
    image:
      "https://images.unsplash.com/photo-1584982751601-97dcc096659c?w=600&q=80",
    description:
      "Fund a fully equipped mobile clinic that will serve 15 remote villages, bringing essential healthcare to 5,000 people who have no access.",
    raised: 62000,
    target: 75000,
    donors: [
      { initials: "DR", color: "#185FA5" },
      { initials: "NP", color: "#7c3fc8" },
      { initials: "YG", color: "#D85A30" },
    ],
    recentDonor: "Dr. Nadia P.",
    recentAmount: "Ghc1,000",
  },
  {
    id: 5,
    title: "Community Arts Centre for Youth",
    category: "arts",
    categoryLabel: "Arts & Culture",
    image:
      "https://images.unsplash.com/photo-1460661419201-fd4cecdf8a8b?w=600&q=80",
    description:
      "Transform an abandoned warehouse into a vibrant creative hub where young artists can learn, perform, and showcase their work for free.",
    raised: 15300,
    target: 30000,
    donors: [
      { initials: "SB", color: "#993556" },
      { initials: "TC", color: "#7c3fc8" },
      { initials: "EW", color: "#BA7517" },
      { initials: "IO", color: "#185FA5" },
    ],
    recentDonor: "Sara B.",
    recentAmount: "Ghc200",
  },
  {
    id: 6,
    title: "Emergency Relief: Flood Victims",
    category: "emergency",
    categoryLabel: "Emergency",
    image:
      "https://images.unsplash.com/photo-1547683905-f686c993aae5?w=600&q=80",
    description:
      "Urgent: Provide food, shelter and medical aid to 800 families displaced by devastating floods in the Northern Region. Act now.",
    raised: 31500,
    target: 35000,
    donors: [
      { initials: "KW", color: "#D85A30" },
      { initials: "AB", color: "#7c3fc8" },
      { initials: "MF", color: "#185FA5" },
      { initials: "TS", color: "#3B6D11" },
    ],
    recentDonor: "Kofi W.",
    recentAmount: "Ghc300",
  },
];

// ── RENDER CARDS ──
function renderCards(data) {
  const grid = document.getElementById("campaignsGrid");
  grid.innerHTML = data
    .map((c) => {
      const pct = Math.round((c.raised / c.target) * 100);
      const raisedFmt = "Ghc" + c.raised.toLocaleString();
      const targetFmt = "Ghc" + c.target.toLocaleString();
      const avatarsHtml = c.donors
        .map(
          (d) =>
            `<div class="donor-av" style="background:${d.color}">${d.initials}</div>`,
        )
        .join("");

      return `
    <div class="campaign-card" data-cat="${c.category}">
      <div class="card-img-wrap">
        <img class="card-img" src="${c.image}" alt="${c.title}" loading="lazy">
        <div class="card-category">${c.categoryLabel}</div>
      </div>
      <div class="card-body">
        <h3 class="card-title">${c.title}</h3>
        <p class="card-desc">${c.description}</p>
        <div class="progress-wrap">
          <div class="progress-bar-bg">
            <div class="progress-bar-fill" style="width:0%" data-width="${pct}%"></div>
          </div>
          <div class="progress-meta">
            <span class="progress-raised">${raisedFmt}</span>
            <span class="progress-pct">${pct}%</span>
          </div>
          <div class="progress-meta" style="margin-top:4px">
            <span class="progress-target" style="font-size:0.8rem;color:var(--muted);">of ${targetFmt} goal</span>
          </div>
        </div>
        <div class="donors-row">
          <div class="donor-avatars">${avatarsHtml}</div>
          <span class="donor-text"><strong>${c.recentDonor}</strong> donated ${c.recentAmount}</span>
        </div>
      </div>
      <div class="card-footer">
        <button class="btn-donate" <button class="btn-donate" onclick="openDonateModal('${c.title}')">Donate now</button>
         <button class="btn btn-ghost report-btn" onclick="reportCampaign('${c.title}')">
  <i class="fa-solid fa-flag"></i> Report
</button>
        
        <div class="share-wrap">
       
          <button class="btn-share" onclick="handleShare(this, '${c.title}')" title="Share campaign">
            <i class="fa-solid fa-share-nodes"></i>
          </button>
          <div class="share-tooltip" id="tip-${c.id}">Link copied!</div>
        </div>
      </div>
    </div>
    `;
    })
    .join("");

  // Animate progress bars after render
  requestAnimationFrame(() => {
    setTimeout(() => {
      document.querySelectorAll(".progress-bar-fill").forEach((bar) => {
        bar.style.width = bar.dataset.width;
      });
    }, 100);
  });
}

// ── FILTER ──
function filterCat(btn, cat) {
  document
    .querySelectorAll(".cat-chip")
    .forEach((b) => b.classList.remove("active"));
  btn.classList.add("active");
  const filtered =
    cat === "all" ? campaigns : campaigns.filter((c) => c.category === cat);
  renderCards(filtered);
  document.getElementById("campaigns").scrollIntoView({ behavior: "smooth" });
}

// ── SHARE ──
function handleShare(btn, title) {
  const url =
    window.location.href +
    "#campaign-" +
    title.toLowerCase().replace(/\s+/g, "-");

  if (navigator.clipboard) {
    navigator.clipboard.writeText(url);
  } else {
    // fallback
    const temp = document.createElement("input");
    document.body.appendChild(temp);
    temp.value = url;
    temp.select();
    document.execCommand("copy");
    document.body.removeChild(temp);
  }

  const tooltip = btn.parentElement.querySelector(".share-tooltip");
  tooltip.classList.add("show");

  setTimeout(() => {
    tooltip.classList.remove("show");
  }, 2000);
}

// ── NAVBAR SCROLL ──
window.addEventListener("scroll", () => {
  document
    .getElementById("navbar")
    .classList.toggle("scrolled", window.scrollY > 20);
});

// ── HAMBURGER ──
const hamburger = document.getElementById("hamburger");
const mobileMenu = document.getElementById("mobileMenu");

hamburger.addEventListener("click", () => {
  hamburger.classList.toggle("active");
  mobileMenu.classList.toggle("active");
});

// ✅ Auto close when resizing to desktop
window.addEventListener("resize", () => {
  if (window.innerWidth >= 768) {
    mobileMenu.classList.remove("active");
  }
});

document.querySelectorAll(".mobile-menu a").forEach((link) => {
  link.addEventListener("click", () => {
    mobileMenu.classList.remove("active");
  });
});

// ── INIT ──
renderCards(campaigns);

function openModal(id) {
  document.getElementById(id).style.display = "block";
  document.body.style.overflow = "hidden";
  // close mobile nav if open
  mobileMenu.classList.remove("active");
}

function closeModal(id) {
  document.getElementById(id).style.display = "none";

  // Only restore scroll if no modals are open
  const anyOpen = [...document.querySelectorAll(".modal")].some(
    (m) => m.style.display === "block",
  );

  if (!anyOpen) {
    document.body.style.overflow = "auto";
  }
}
// Close when clicking outside
window.onclick = function (e) {
  document.querySelectorAll(".modal").forEach((modal) => {
    if (e.target === modal) {
      modal.style.display = "none";
      document.body.style.overflow = "auto";
    }
  });
};

// Close with ESC key
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    document.querySelectorAll(".modal").forEach((modal) => {
      modal.style.display = "none";
      document.body.style.overflow = "auto";
    });
  }
});

// ── AUTH TOGGLE (Sign in ↔ Sign up) ──
let isSignup = false;

function toggleAuthMode(e) {
  e.preventDefault();
  isSignup = !isSignup;

  const title = document.getElementById("authTitle");
  const toggleText = document.getElementById("authToggleText");

  if (isSignup) {
    title.textContent = "Sign Up";
    toggleText.textContent = "Already have an account?";
  } else {
    title.textContent = "Sign In";
    toggleText.textContent = "Don’t have an account?";
  }
}

function setAmount(val) {
  document.getElementById("donationAmount").value = val;
}

function openDonateModal(title) {
  openModal("donateModal");

  const titleEl = document.getElementById("donateCampaignTitle");
  const input = document.getElementById("donationAmount");

  titleEl.textContent = title;
  input.value = "";
}

function switchModal(closeId, openId) {
  closeModal(closeId);
  openModal(openId);
}

function reportCampaign(title) {
  document.getElementById("reportCampaignTitle").innerText = title;
  openModal("reportModal");
}

document.getElementById("year").textContent = new Date().getFullYear();
