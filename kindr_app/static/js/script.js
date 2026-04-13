let campaigns = [];
let pendingRequests = 0;
let campaignPreviewObjectUrl = null;
const OTP_RESEND_COOLDOWN_SECONDS = 60;
let otpResendCountdownTimer = null;
let otpResendSecondsLeft = 0;

function fmtCompact(n) {
  const num = Number(n) || 0;
  if (num >= 1000000) return `${Math.round((num / 1000000) * 10) / 10}M`;
  if (num >= 1000) return `${Math.round((num / 1000) * 10) / 10}K`;
  return String(Math.round(num));
}

function escHtml(s) {
  if (s == null) {
    return "";
  }
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

async function loadCampaigns() {
  const grid = document.getElementById("campaignsGrid");
  if (!grid) {
    return;
  }
  const { res, data } = await apiJson("/api/campaigns");
  if (!res.ok) {
    grid.innerHTML =
      '<p class="campaigns-load-error" style="padding:24px;color:var(--muted)">Could not load campaigns.</p>';
    return;
  }
  campaigns = data.campaigns || [];
  document.querySelectorAll(".cat-chip").forEach((b) => b.classList.remove("active"));
  const chips = document.querySelectorAll(".cat-chip");
  if (chips.length) {
    chips[0].classList.add("active");
  }
  renderCards(campaigns);
}

async function loadHomeStats(silentLoader = false) {
  const raisedEl = document.getElementById("statTotalRaised");
  const campaignEl = document.getElementById("statCampaignCount");
  const donorEl = document.getElementById("statDonorCount");
  if (!raisedEl && !campaignEl && !donorEl) return;
  const { res, data } = await apiJson("/api/stats", { silentLoader });
  if (!res.ok || !data) return;
  if (raisedEl) raisedEl.textContent = `Ghc${fmtCompact(data.total_raised || 0)}`;
  if (campaignEl) campaignEl.textContent = fmtCompact(data.campaigns_count || 0);
  if (donorEl) donorEl.textContent = fmtCompact(data.donors_count || 0);
}

let cachedUserEmail = "";

function setGlobalLoader(active) {
  const el = document.getElementById("globalLoader");
  if (!el) return;
  el.classList.toggle("show", !!active);
}

function csrfHeaders() {
  const t = document.querySelector('meta[name="csrf-token"]');
  const h = { "Content-Type": "application/json" };
  const token = t && t.getAttribute("content");
  if (token) {
    h["X-CSRFToken"] = token;
    h["X-CSRF-Token"] = token;
  }
  return h;
}

async function refreshCsrfToken() {
  try {
    const res = await fetch("/api/auth/csrf-token", { credentials: "include" });
    if (!res.ok) return false;
    const data = await res.json().catch(() => ({}));
    if (!data.csrf_token) return false;
    let meta = document.querySelector('meta[name="csrf-token"]');
    if (!meta) {
      meta = document.createElement("meta");
      meta.setAttribute("name", "csrf-token");
      document.head.appendChild(meta);
    }
    meta.setAttribute("content", data.csrf_token);
    return true;
  } catch {
    return false;
  }
}

async function apiJson(path, opts = {}) {
  const { headers: optHeaders, _retriedCsrf, silentLoader, ...rest } = opts;
  let res;
  if (!silentLoader) {
    pendingRequests += 1;
    setGlobalLoader(true);
  }
  try {
    res = await fetch(path, {
      ...rest,
      credentials: "include",
      headers: { ...csrfHeaders(), ...(optHeaders || {}) },
    });
  } catch (err) {
    console.error(err);
    return {
      res: { ok: false, status: 0 },
      data: { message: "Network error — is the server running?" },
    };
  } finally {
    if (!silentLoader) {
      pendingRequests = Math.max(0, pendingRequests - 1);
      setGlobalLoader(pendingRequests > 0);
    }
  }
  const text = await res.text();
  let data = {};
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = {
        message: text.includes("CSRF")
          ? "Security token missing — refresh the page and try again."
          : text.slice(0, 180) || res.statusText,
      };
    }
  }
  const msg = String((data && data.message) || "");
  const csrfError =
    res.status === 400 &&
    (msg.includes("Security token") || msg.includes("CSRF") || msg.includes("csrf"));
  if (csrfError) {
    if (!_retriedCsrf) {
      const refreshed = await refreshCsrfToken();
      if (refreshed) {
        return apiJson(path, { ...opts, _retriedCsrf: true });
      }
    }
    data.message = "Security token expired. Please refresh the page and try again.";
  }
  return { res, data };
}

function showToast(msg, isError) {
  const el = document.getElementById("toast");
  if (!el) {
    alert(msg);
    return;
  }
  el.textContent = msg;
  el.classList.toggle("toast-error", !!isError);
  el.classList.add("show");
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => el.classList.remove("show"), 5000);
}

function clearOtpResendTimer() {
  if (otpResendCountdownTimer) {
    clearInterval(otpResendCountdownTimer);
    otpResendCountdownTimer = null;
  }
}

function setOtpResendUi(secondsLeft) {
  const btn = document.getElementById("otpResendBtn");
  if (!btn) return;
  if (secondsLeft > 0) {
    btn.disabled = true;
    btn.textContent = `Resend code in ${secondsLeft}s`;
  } else {
    btn.disabled = false;
    btn.textContent = "Resend code";
  }
}

function startOtpResendCooldown(seconds = OTP_RESEND_COOLDOWN_SECONDS) {
  otpResendSecondsLeft = Math.max(0, Number(seconds) || 0);
  clearOtpResendTimer();
  setOtpResendUi(otpResendSecondsLeft);
  if (otpResendSecondsLeft <= 0) return;
  otpResendCountdownTimer = setInterval(() => {
    otpResendSecondsLeft = Math.max(0, otpResendSecondsLeft - 1);
    setOtpResendUi(otpResendSecondsLeft);
    if (otpResendSecondsLeft <= 0) clearOtpResendTimer();
  }, 1000);
}

const ERR_MESSAGES = {
  account_suspended:
    "This account has been suspended. Contact support if you think this is a mistake.",
  google_oauth_not_configured: "Google sign-in is not configured on the server.",
  facebook_oauth_not_configured: "Facebook sign-in is not configured on the server.",
  apple_oauth_not_configured: "Apple sign-in is not configured on the server.",
  google_login_failed: "Google sign-in failed. Try again.",
  facebook_login_failed: "Facebook sign-in failed. Try again.",
  apple_login_failed: "Apple sign-in failed. Try again.",
  google_profile_failed: "Could not load your Google profile.",
  facebook_profile_failed: "Could not load your Facebook profile.",
  facebook_email_required:
    "Facebook did not share an email. Grant email permission or use another method.",
  google_email_missing: "Google did not return an email address.",
  google_token_missing: "Google authentication incomplete.",
  facebook_token_missing: "Facebook authentication incomplete.",
  apple_token_missing: "Apple authentication incomplete.",
  apple_token_invalid: "Invalid Apple token.",
  apple_profile_failed: "Could not read Apple profile.",
  apple_email_first_login:
    "Apple only shares your email on first sign-in. Use email login or contact support.",
};

function readQueryFlags() {
  const p = new URLSearchParams(window.location.search);
  if (p.get("_") === "logout") {
    showToast("You are signed out.");
    updateUI(null);
  }
  const err = p.get("error");
  if (err && ERR_MESSAGES[err]) {
    showToast(ERR_MESSAGES[err], true);
  }
  if (p.get("next") === "start_campaign") {
    try {
      sessionStorage.setItem("kindr_post_login", "start_campaign");
    } catch {
      /* ignore */
    }
  }
  const openCampaignParam = p.get("open_campaign");
  if (p.get("login") === "1" || p.get("signin") === "1") {
    openModal("signinModal");
  }
  const donation = p.get("donation");
  if (donation === "success") {
    showToast("Thank you — your donation was recorded.");
    void loadCampaigns();
  } else if (donation === "failed" || donation === "missing_ref") {
    showToast("Payment was not completed. Try again or contact support if you were charged.", true);
  }
  if (p.get("oauth") === "pending") {
    void handleOAuthPending();
  }
  if (window.history.replaceState) {
    const u = new URL(window.location.href);
    u.search = "";
    window.history.replaceState({}, "", u.pathname + u.hash);
  }
  if (openCampaignParam === "1") {
    void openCampaignFlow();
  }
}

let otpContext = { purpose: "", email: "" };

function openOtpModal(purpose, email, title, hint) {
  otpContext = { purpose, email: email || "" };
  document.getElementById("otpModalTitle").textContent = title || "Enter verification code";
  document.getElementById("otpModalHint").textContent = hint || "";
  document.getElementById("otpPurpose").value = purpose;
  const em = document.getElementById("otpEmail");
  if (em) {
    em.value = email || "";
    em.readOnly = true;
  }
  document.getElementById("otpCode").value = "";
  startOtpResendCooldown();
  openModal("otpModal");
}

async function submitOtp() {
  const code = document.getElementById("otpCode").value.trim();
  const purpose = document.getElementById("otpPurpose").value;
  let email = document.getElementById("otpEmail").value.trim().toLowerCase();
  if (!code) {
    showToast("Enter the verification code.", true);
    return;
  }
  if (purpose !== "campaign_register" && !email) {
    showToast("Email is required.", true);
    return;
  }
  const body = { code, purpose };
  if (purpose !== "campaign_register") {
    body.email = email;
  }
  const { res, data } = await apiJson("/api/auth/verify-otp", {
    method: "POST",
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    showToast(data.message || "Verification failed.", true);
    return;
  }
  closeModal("otpModal");
  if (data.user) {
    updateUI(data.user);
    showToast("Signed in successfully.");
    let post = null;
    try {
      post = sessionStorage.getItem("kindr_post_login");
      if (post) {
        sessionStorage.removeItem("kindr_post_login");
      }
    } catch {
      post = null;
    }
    if (post === "start_campaign") {
      void openCampaignFlow();
      return;
    }
    window.location.href = "/dashboard";
  }
}

async function resendOtp() {
  if (otpResendSecondsLeft > 0) {
    return;
  }
  const purpose = document.getElementById("otpPurpose").value;
  const email = document.getElementById("otpEmail").value.trim().toLowerCase();
  if (!email || !["register", "login", "oauth_complete"].includes(purpose)) {
    showToast("Cannot resend for this step from here.", true);
    return;
  }
  const { res, data } = await apiJson("/api/auth/resend-otp", {
    method: "POST",
    body: JSON.stringify({ email, purpose }),
  });
  if (!res.ok) {
    showToast(data.message || "Could not resend.", true);
    return;
  }
  if (data.dev_otp) {
    showToast(`Dev OTP: ${data.dev_otp}`, true);
  }
  showToast(data.message || "Code sent.");
  startOtpResendCooldown();
}

async function submitSignup() {
  const name = document.getElementById("signupName").value.trim();
  const email = document.getElementById("signupEmail").value.trim().toLowerCase();
  const phone = document.getElementById("signupPhone").value.trim();
  const password = document.getElementById("signupPassword").value;
  const password2 = document.getElementById("signupPassword2").value;
  if (!name || !email || !password) {
    showToast("Fill in name, email, and password.", true);
    return;
  }
  if (password !== password2) {
    showToast("Passwords do not match.", true);
    return;
  }
  const { res, data } = await apiJson("/api/auth/register", {
    method: "POST",
    body: JSON.stringify({ name, email, password, phone: phone || null }),
  });
  if (!res.ok) {
    showToast(data.message || "Signup failed.", true);
    return;
  }
  if (data.dev_otp) {
    showToast(
      `Your verification code (shown on screen for local testing): ${data.dev_otp}`,
      true,
    );
  }
  closeModal("signupModal");
  openOtpModal(
    "register",
    email,
    "Verify your email",
    data.message || "Enter the code we sent you.",
  );
}

async function submitSignin() {
  const identifier = document.getElementById("signinEmail").value.trim();
  const password = document.getElementById("signinPassword").value;
  if (!identifier || !password) {
    showToast("Enter your email or phone and password.", true);
    return;
  }
  const { res, data } = await apiJson("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ email: identifier, password }),
  });
  if (!res.ok) {
    showToast(data.message || "Login failed.", true);
    return;
  }
  if (data.requires_otp) {
    if (data.dev_otp) {
      showToast(
        `Your verification code (shown on screen for local testing): ${data.dev_otp}`,
        true,
      );
    }
    closeModal("signinModal");
    openOtpModal(
      data.purpose || "login",
      data.email || "",
      "Verification required",
      data.message || "Enter your one-time code.",
    );
    return;
  }
  showToast("Unexpected response from server. Refresh the page and try again.", true);
}

async function requestPasswordResetCode() {
  const identifier = (document.getElementById("resetIdentifier")?.value || "").trim();
  if (!identifier) {
    showToast("Enter your email or phone.", true);
    return;
  }
  const { res, data } = await apiJson("/api/auth/request-password-reset", {
    method: "POST",
    body: JSON.stringify({ identifier }),
  });
  if (!res.ok) {
    showToast(data.message || "Could not send reset code.", true);
    return;
  }
  if (data.email) {
    const em = document.getElementById("resetEmail");
    if (em) em.value = data.email;
  }
  if (data.dev_otp) {
    showToast(`Reset code (local testing): ${data.dev_otp}`, true);
  }
  showToast(data.message || "Reset code sent.");
}

async function submitPasswordReset() {
  const email = (document.getElementById("resetEmail")?.value || "").trim().toLowerCase();
  const code = (document.getElementById("resetCode")?.value || "").trim();
  const new_password = document.getElementById("resetNewPassword")?.value || "";
  if (!email || !code || !new_password) {
    showToast("Enter email, code, and new password.", true);
    return;
  }
  const { res, data } = await apiJson("/api/auth/reset-password", {
    method: "POST",
    body: JSON.stringify({ email, code, new_password }),
  });
  if (!res.ok) {
    showToast(data.message || "Could not reset password.", true);
    return;
  }
  closeModal("forgotPasswordModal");
  showToast(data.message || "Password changed.");
  openModal("signinModal");
}

function oauthStartUrl(path) {
  let url = path;
  try {
    if (sessionStorage.getItem("kindr_post_login") === "start_campaign") {
      url += (path.includes("?") ? "&" : "?") + "next=start_campaign";
    }
  } catch {
    /* ignore */
  }
  return url;
}

function goGoogle() {
  window.location.href = oauthStartUrl("/auth/google");
}
function goFacebook() {
  window.location.href = oauthStartUrl("/auth/facebook");
}
function goApple() {
  window.location.href = oauthStartUrl("/auth/apple");
}

async function handleOAuthPending() {
  const { res, data } = await apiJson("/api/auth/oauth-pending");
  if (!res.ok || !data.pending) {
    return;
  }
  openOtpModal(
    "oauth_complete",
    data.email,
    "Verify it’s you",
    "We sent a code to your email to finish signing in with your social account.",
  );
}

async function refreshUser() {
  const { res, data } = await apiJson("/api/auth/me");
  if (!res.ok) {
    updateUI(null);
    return;
  }
  if (data.user) {
    updateUI(data.user);
  } else {
    updateUI(null);
  }
}

function updateUI(user) {
  const authButtons = document.getElementById("authButtons");
  const userProfile = document.getElementById("userProfile");
  const userName = document.getElementById("userName");
  const userAvatar = document.getElementById("userAvatar");
  const adminLink = document.getElementById("adminNavLink");
  const mobileMenuGuest = document.getElementById("mobileMenuGuest");
  const mobileMenuAccount = document.getElementById("mobileMenuAccount");
  const mobileMenuUserName = document.getElementById("mobileMenuUserName");
  const mobileMenuAdminLink = document.getElementById("mobileMenuAdminLink");
  if (!authButtons || !userProfile) {
    return;
  }
  authButtons.style.removeProperty("display");
  userProfile.style.removeProperty("display");
  if (user) {
    cachedUserEmail = user.email || "";
    authButtons.toggleAttribute("hidden", true);
    userProfile.toggleAttribute("hidden", false);
    userName.textContent = user.name;
    userAvatar.textContent = (user.name || "U").charAt(0).toUpperCase();
    if (adminLink) {
      adminLink.toggleAttribute("hidden", !user.is_admin);
    }
    if (mobileMenuGuest) {
      mobileMenuGuest.toggleAttribute("hidden", true);
    }
    if (mobileMenuAccount) {
      mobileMenuAccount.toggleAttribute("hidden", false);
      if (mobileMenuUserName) {
        mobileMenuUserName.textContent = user.name || "";
      }
      if (mobileMenuAdminLink) {
        mobileMenuAdminLink.toggleAttribute("hidden", !user.is_admin);
      }
    }
  } else {
    cachedUserEmail = "";
    authButtons.toggleAttribute("hidden", false);
    userProfile.toggleAttribute("hidden", true);
    if (adminLink) {
      adminLink.toggleAttribute("hidden", true);
    }
    if (mobileMenuGuest) {
      mobileMenuGuest.toggleAttribute("hidden", false);
    }
    if (mobileMenuAccount) {
      mobileMenuAccount.toggleAttribute("hidden", true);
    }
    if (userName) {
      userName.textContent = "User";
    }
    if (userAvatar) {
      userAvatar.textContent = "U";
    }
  }
}

function logout() {
  try {
    sessionStorage.removeItem("kindr_post_login");
  } catch {
    /* ignore */
  }
  const profileDd = document.getElementById("profileDropdown");
  if (profileDd) {
    profileDd.classList.remove("show");
  }
  updateUI(null);
  const logoutUrl =
    (typeof document !== "undefined" &&
      document.body &&
      document.body.getAttribute("data-logout-url")) ||
    "/logout";
  window.location.replace(logoutUrl);
}

function _revokeCampaignPreviewUrl() {
  if (campaignPreviewObjectUrl) {
    URL.revokeObjectURL(campaignPreviewObjectUrl);
    campaignPreviewObjectUrl = null;
  }
}

function updateCampaignImagePreview() {
  const wrap = document.getElementById("campaignImagePreviewWrap");
  const img = document.getElementById("campaignImagePreview");
  const fileEl = document.getElementById("campaignImageFile");
  const urlEl = document.getElementById("campaignImage");
  if (!wrap || !img) return;
  const file = fileEl && fileEl.files && fileEl.files[0] ? fileEl.files[0] : null;
  _revokeCampaignPreviewUrl();
  if (file && file.type.startsWith("image/")) {
    campaignPreviewObjectUrl = URL.createObjectURL(file);
    img.src = campaignPreviewObjectUrl;
    img.classList.remove("is-fade");
    wrap.hidden = false;
    return;
  }
  const u = (urlEl && urlEl.value.trim()) || "";
  if (/^https?:\/\//i.test(u) || (u.startsWith("/") && u.length > 1)) {
    img.src = u;
    img.classList.remove("is-fade");
    wrap.hidden = false;
    return;
  }
  img.removeAttribute("src");
  wrap.hidden = true;
}

function resetCampaignModal() {
  const gate = document.getElementById("campaignGate");
  const otpSec = document.getElementById("campaignOtpSection");
  const formSec = document.getElementById("campaignFormSection");
  if (gate) gate.style.display = "block";
  if (otpSec) otpSec.style.display = "none";
  if (formSec) formSec.style.display = "none";
  [
    "campaignOtpInput",
    "campaignTitle",
    "campaignCategory",
    "campaignGoal",
    "campaignStartDate",
    "campaignEndDate",
    "campaignImage",
    "campaignDesc",
  ].forEach(
    (id) => {
      const el = document.getElementById(id);
      if (el) {
        el.value = "";
      }
    },
  );
  const fileEl = document.getElementById("campaignImageFile");
  if (fileEl) fileEl.value = "";
  _revokeCampaignPreviewUrl();
  const prevImg = document.getElementById("campaignImagePreview");
  const prevWrap = document.getElementById("campaignImagePreviewWrap");
  if (prevImg) prevImg.removeAttribute("src");
  if (prevWrap) prevWrap.hidden = true;
}

function closeCampaignModal() {
  closeModal("campaignModal");
  resetCampaignModal();
}

async function openCampaignFlow() {
  const { res, data } = await apiJson("/api/auth/me");
  if (!res.ok || !data.user) {
    try {
      sessionStorage.setItem("kindr_post_login", "start_campaign");
    } catch {
      /* ignore */
    }
    window.location.href = "/start-campaign";
    return;
  }
  resetCampaignModal();
  const startEl = document.getElementById("campaignStartDate");
  if (startEl && !startEl.value) {
    const d = new Date();
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    const dd = String(d.getDate()).padStart(2, "0");
    startEl.value = `${d.getFullYear()}-${mm}-${dd}`;
  }
  openModal("campaignModal");
}

async function sendCampaignStepOtp() {
  const { res, data } = await apiJson("/api/auth/send-campaign-otp", {
    method: "POST",
    body: "{}",
  });
  if (res.status === 401) {
    showToast("Please sign in again.", true);
    return;
  }
  if (!res.ok) {
    showToast(data.message || "Could not send code.", true);
    return;
  }
  document.getElementById("campaignGate").style.display = "none";
  document.getElementById("campaignOtpSection").style.display = "block";
  showToast(data.message || "Code sent.");
}

async function verifyCampaignStepOtp() {
  const code = document.getElementById("campaignOtpInput").value.trim();
  if (!code) {
    showToast("Enter the code.", true);
    return;
  }
  const { res, data } = await apiJson("/api/auth/verify-otp", {
    method: "POST",
    body: JSON.stringify({ code, purpose: "campaign_register" }),
  });
  if (!res.ok) {
    showToast(data.message || "Invalid or expired code.", true);
    return;
  }
  document.getElementById("campaignOtpSection").style.display = "none";
  document.getElementById("campaignFormSection").style.display = "block";
  showToast("Code verified. Complete your campaign details.");
}

async function submitCampaignForm() {
  const title = document.getElementById("campaignTitle").value.trim();
  const category = document.getElementById("campaignCategory").value.trim();
  const goal_amount = document.getElementById("campaignGoal").value;
  const start_date = document.getElementById("campaignStartDate").value;
  const end_date = document.getElementById("campaignEndDate").value;
  let image_url = document.getElementById("campaignImage").value.trim();
  const imageFileEl = document.getElementById("campaignImageFile");
  const description = document.getElementById("campaignDesc").value.trim();
  if (!category) {
    showToast("Please choose a campaign category.", true);
    return;
  }
  if (!start_date || !end_date) {
    showToast("Select creation date and completion date.", true);
    return;
  }
  if (end_date <= start_date) {
    showToast("Completion date must be after creation date.", true);
    return;
  }
  if (imageFileEl && imageFileEl.files && imageFileEl.files.length > 0) {
    const fd = new FormData();
    fd.append("image", imageFileEl.files[0]);
    const tokenMeta = document.querySelector('meta[name="csrf-token"]');
    const token = tokenMeta ? tokenMeta.getAttribute("content") : "";
    pendingRequests += 1;
    setGlobalLoader(true);
    let uploadRes;
    let uploadData = {};
    try {
      uploadRes = await fetch("/api/uploads/campaign-image", {
        method: "POST",
        credentials: "include",
        headers: token ? { "X-CSRFToken": token, "X-CSRF-Token": token } : {},
        body: fd,
      });
      uploadData = await uploadRes.json().catch(() => ({}));
    } catch {
      pendingRequests = Math.max(0, pendingRequests - 1);
      setGlobalLoader(pendingRequests > 0);
      showToast("Could not upload image. Check your network and try again.", true);
      return;
    }
    pendingRequests = Math.max(0, pendingRequests - 1);
    setGlobalLoader(pendingRequests > 0);
    if (!uploadRes.ok || !uploadData.url) {
      showToast(uploadData.message || "Image upload failed.", true);
      return;
    }
    image_url = uploadData.url;
  }
  const { res, data } = await apiJson("/api/campaigns", {
    method: "POST",
    body: JSON.stringify({
      title,
      category,
      goal_amount,
      start_date,
      end_date,
      image_url: image_url || null,
      description,
    }),
  });
  if (res.status === 403) {
    showToast(data.message || "Verify the security code first.", true);
    return;
  }
  if (!res.ok) {
    showToast(data.message || "Could not create campaign.", true);
    return;
  }
  showToast(data.message || "Campaign created.");
  closeCampaignModal();
  void loadCampaigns();
}

function renderCards(data) {
  const grid = document.getElementById("campaignsGrid");
  if (!grid) {
    return;
  }
  if (!data.length) {
    grid.innerHTML =
      '<p class="campaigns-empty" style="padding:24px;color:var(--muted)">No campaigns yet. Be the first to start one.</p>';
    return;
  }
  grid.innerHTML = data
    .map((c, i) => {
      const raised = Number(c.raised) || 0;
      const target = Number(c.target) || 1;
      const pct = Math.min(100, Math.round((raised / target) * 100));
      const raisedFmt = "Ghc" + raised.toLocaleString();
      const targetFmt = "Ghc" + target.toLocaleString();
      const dc = Number(c.donor_count) || 0;
      const donorText =
        dc === 0
          ? "Be the first to donate"
          : `${dc} donor${dc === 1 ? "" : "s"} so far`;
      const recentPayments = Array.isArray(c.recent_payments) ? c.recent_payments : [];
      const paymentHtml = recentPayments.length
        ? `<ul class="recent-payments-list">${recentPayments
            .map((p) => {
              const n = escHtml(p.name || "Anonymous donor");
              const a = Number(p.amount || 0).toLocaleString(undefined, {
                minimumFractionDigits: 0,
                maximumFractionDigits: 2,
              });
              const t = escHtml(p.ago || "recently");
              return `<li><span>${n}</span><strong>Ghc${a}</strong><em>${t}</em></li>`;
            })
            .join("")}</ul>`
        : `<div class="recent-payments-empty">No recent payments yet.</div>`;

      const titleAttr = encodeURIComponent(c.title ?? "");
      const tEsc = escHtml(c.title);
      const dEsc = escHtml(c.description);
      const labEsc = escHtml(c.category_label || c.category);
      const imgRaw = String(c.image || "");
      const isAbsoluteHttp = /^https?:\/\//i.test(imgRaw);
      const isLocalStatic = imgRaw.startsWith("/");
      const safeImg = isAbsoluteHttp || isLocalStatic
        ? imgRaw.replace(/"/g, "&quot;")
        : "https://images.unsplash.com/photo-1559027615-cd4628902d4a?w=600&q=80";
      const catSlug = String(c.category || "community").replace(/[^a-z0-9_-]/gi, "");
      const cardDelay = Math.min(i * 48, 520);
      return `
    <div class="campaign-card anim-card-reveal" data-cat="${catSlug}" style="animation-delay:${cardDelay}ms">
      <div class="card-img-wrap">
        <img class="card-img" src="${safeImg}" alt="${tEsc}" loading="lazy" onload="this.closest('.campaign-card')?.classList.add('img-ready')">
        <div class="card-category">${labEsc}</div>
      </div>
      <div class="card-body">
        <h3 class="card-title">${tEsc}</h3>
        <p class="card-desc">${dEsc}</p>
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
          <div class="donor-avatars"></div>
          <span class="donor-text">${donorText}</span>
        </div>
        <div class="recent-payments">
          <div class="recent-payments-title">Recent payments</div>
          ${paymentHtml}
        </div>
      </div>
      <div class="card-footer">
        <button type="button" class="btn-donate" data-cid="${c.id}" data-title="${titleAttr}">
          Donate now
        </button>
         <button type="button" class="btn btn-ghost report-btn" data-title="${titleAttr}">
  <i class="fa-solid fa-flag"></i> Report
</button>
        <div class="share-wrap">
          <button type="button" class="btn-share" data-title="${titleAttr}" title="Share campaign">
            <i class="fa-solid fa-share-nodes"></i>
          </button>
          <div class="share-tooltip" id="tip-${c.id}">Link copied!</div>
        </div>
      </div>
    </div>
    `;
    })
    .join("");

  requestAnimationFrame(() => {
    setTimeout(() => {
      document.querySelectorAll(".progress-bar-fill").forEach((bar) => {
        bar.style.width = bar.dataset.width;
      });
    }, 100);
  });
}

function filterCat(btn, cat) {
  document.querySelectorAll(".cat-chip").forEach((b) => b.classList.remove("active"));
  btn.classList.add("active");
  const filtered =
    cat === "all" ? campaigns : campaigns.filter((c) => c.category === cat);
  renderCards(filtered);
  document.getElementById("campaigns").scrollIntoView({ behavior: "smooth" });
}

function handleShare(btn, title) {
  const url =
    window.location.href.split("#")[0] +
    "#campaign-" +
    title.toLowerCase().replace(/\s+/g, "-");

  if (navigator.clipboard) {
    navigator.clipboard.writeText(url);
  } else {
    const temp = document.createElement("input");
    document.body.appendChild(temp);
    temp.value = url;
    temp.select();
    document.execCommand("copy");
    document.body.removeChild(temp);
  }

  const tooltip = btn.parentElement.querySelector(".share-tooltip");
  if (tooltip) {
    tooltip.classList.add("show");
    setTimeout(() => tooltip.classList.remove("show"), 2000);
  }
}

function initCampaignGridActions() {
  const grid = document.getElementById("campaignsGrid");
  if (!grid || grid.dataset.kindrActionsBound) {
    return;
  }
  grid.dataset.kindrActionsBound = "1";
  grid.addEventListener("click", (e) => {
    const donate = e.target.closest(".btn-donate");
    if (donate) {
      e.preventDefault();
      const id = parseInt(donate.getAttribute("data-cid") || "", 10);
      let title = "";
      try {
        title = decodeURIComponent(donate.getAttribute("data-title") || "");
      } catch {
        title = "";
      }
      openDonateModal(Number.isNaN(id) ? null : id, title);
      return;
    }
    const reportBtn = e.target.closest(".report-btn");
    if (reportBtn) {
      e.preventDefault();
      let title = "";
      try {
        title = decodeURIComponent(reportBtn.getAttribute("data-title") || "");
      } catch {
        title = "";
      }
      reportCampaign(title);
      return;
    }
    const shareBtn = e.target.closest(".btn-share");
    if (shareBtn) {
      let title = "";
      try {
        title = decodeURIComponent(shareBtn.getAttribute("data-title") || "");
      } catch {
        title = "";
      }
      handleShare(shareBtn, title);
    }
  });
}

function initDashboardCampaignActions() {
  const donateBtns = document.querySelectorAll(".dashboard-donate");
  const shareBtns = document.querySelectorAll(".dashboard-share");
  if (!donateBtns.length && !shareBtns.length) {
    return;
  }
  donateBtns.forEach((btn) => {
    if (btn.dataset.kindrBound) return;
    btn.dataset.kindrBound = "1";
    btn.addEventListener("click", () => {
      const id = parseInt(btn.getAttribute("data-cid") || "", 10);
      let title = "";
      try {
        title = decodeURIComponent(btn.getAttribute("data-title") || "");
      } catch {
        title = "";
      }
      openDonateModal(Number.isNaN(id) ? null : id, title);
    });
  });
  shareBtns.forEach((btn) => {
    if (btn.dataset.kindrBound) return;
    btn.dataset.kindrBound = "1";
    btn.addEventListener("click", () => {
      let title = "";
      try {
        title = decodeURIComponent(btn.getAttribute("data-title") || "");
      } catch {
        title = "";
      }
      handleShare(btn, title);
    });
  });
}

function initProgressBars() {
  const bars = document.querySelectorAll(".progress-bar-fill[data-width]");
  if (!bars.length) return;
  requestAnimationFrame(() => {
    setTimeout(() => {
      bars.forEach((bar) => {
        bar.style.width = bar.dataset.width || "0%";
      });
    }, 80);
  });
}

function refreshDashboardCampaigns(data) {
  const rows = document.querySelectorAll(".dashboard-campaign-card[data-campaign-id]");
  if (!rows.length || !Array.isArray(data)) return;
  const byId = new Map(data.map((c) => [Number(c.id), c]));
  rows.forEach((row) => {
    const id = Number(row.getAttribute("data-campaign-id"));
    if (!id || !byId.has(id)) return;
    const c = byId.get(id);
    const raised = Number(c.raised) || 0;
    const goal = Number(c.target) || 1;
    const pct = Math.max(0, Math.min(100, Math.round((raised / goal) * 100)));
    const donors = Number(c.donor_count) || 0;
    const net = Math.max(0, raised - raised * 0.07);

    const raisedCell = row.querySelector(".dashboard-raised");
    const donorsCell = row.querySelector(".dashboard-donors");
    const goalCell = row.querySelector(".dashboard-goal");
    const progressRaised = row.querySelector(".dashboard-progress-raised");
    const progressPct = row.querySelector(".dashboard-progress-pct");
    const bar = row.querySelector(".progress-bar-fill");
    const netEl = row.querySelector(".d-cc-net");

    if (raisedCell) raisedCell.textContent = `Ghc${Math.round(raised).toLocaleString()}`;
    if (donorsCell) donorsCell.textContent = `${donors}`;
    if (goalCell) goalCell.textContent = `Ghc${Math.round(goal).toLocaleString()}`;
    if (progressRaised) progressRaised.textContent = `Ghc${Math.round(raised).toLocaleString()}`;
    if (progressPct) progressPct.textContent = `${pct}%`;
    if (netEl) {
      netEl.innerHTML = `<strong>Ghc${net.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</strong>`;
    }
    if (bar) {
      bar.dataset.width = `${pct}%`;
      bar.style.width = `${pct}%`;
    }
  });
}

function startLiveDonationUpdates() {
  const hasCampaignGrid = !!document.getElementById("campaignsGrid");
  const hasDashboardRows =
    document.querySelectorAll(".dashboard-campaign-card[data-campaign-id]").length > 0;
  const hasHomeStats =
    !!document.getElementById("statTotalRaised") ||
    !!document.getElementById("statCampaignCount") ||
    !!document.getElementById("statDonorCount");
  if (!hasCampaignGrid && !hasDashboardRows && !hasHomeStats) {
    return;
  }
  let busy = false;
  const tick = async () => {
    if (busy || document.hidden) return;
    busy = true;
    const { res, data } = await apiJson("/api/campaigns", { silentLoader: true });
    if (res.ok && data && Array.isArray(data.campaigns)) {
      if (document.getElementById("campaignsGrid")) {
        campaigns = data.campaigns;
        renderCards(campaigns);
      }
      refreshDashboardCampaigns(data.campaigns);
      void loadHomeStats(true);
    }
    busy = false;
  };
  setInterval(tick, 15000);
}

window.addEventListener("scroll", () => {
  const nav = document.getElementById("navbar");
  if (nav) {
    nav.classList.toggle("scrolled", window.scrollY > 20);
  }
});

const hamburger = document.getElementById("hamburger");
const mobileMenu = document.getElementById("mobileMenu");
if (hamburger && mobileMenu) {
  hamburger.addEventListener("click", () => {
    hamburger.classList.toggle("active");
    mobileMenu.classList.toggle("active");
  });
}

window.addEventListener("resize", () => {
  if (window.innerWidth >= 768 && mobileMenu) {
    mobileMenu.classList.remove("active");
  }
});

document.querySelectorAll(".mobile-menu a").forEach((link) => {
  link.addEventListener("click", () => {
    if (mobileMenu) {
      mobileMenu.classList.remove("active");
    }
  });
});

function initCampaignImagePreview() {
  const fileEl = document.getElementById("campaignImageFile");
  const urlEl = document.getElementById("campaignImage");
  if (!fileEl || fileEl.dataset.kindrPreviewBound) return;
  fileEl.dataset.kindrPreviewBound = "1";
  if (urlEl) {
    urlEl.dataset.kindrPreviewBound = "1";
    urlEl.addEventListener("input", () => {
      const f = document.getElementById("campaignImageFile");
      if (f && f.files && f.files.length) return;
      updateCampaignImagePreview();
    });
  }
  fileEl.addEventListener("change", updateCampaignImagePreview);
}

initCampaignGridActions();
initDashboardCampaignActions();
initProgressBars();
initCampaignImagePreview();
startLiveDonationUpdates();
void loadCampaigns();
void loadHomeStats();

function modalIsOpen(el) {
  const d = el.style.display;
  return d === "flex" || d === "block";
}

function openModal(id) {
  const m = document.getElementById(id);
  if (m) {
    m.style.display = "flex";
    document.body.style.overflow = "hidden";
    const content = m.querySelector(".modal-content");
    if (content) {
      content.classList.remove("anim-modal-pop");
      void content.offsetWidth;
      content.classList.add("anim-modal-pop");
    }
  }
  if (mobileMenu) {
    mobileMenu.classList.remove("active");
  }
}

function closeModal(id) {
  const m = document.getElementById(id);
  if (m) {
    m.style.display = "none";
  }
  const anyOpen = [...document.querySelectorAll(".modal")].some(modalIsOpen);
  if (!anyOpen) {
    document.body.style.overflow = "auto";
  }
}

window.onclick = function (e) {
  document.querySelectorAll(".modal").forEach((modal) => {
    if (e.target === modal) {
      modal.style.display = "none";
    }
  });
  const anyStillOpen = [...document.querySelectorAll(".modal")].some(modalIsOpen);
  if (!anyStillOpen) {
    document.body.style.overflow = "auto";
  }
};

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    document.querySelectorAll(".modal").forEach((modal) => {
      modal.style.display = "none";
    });
    document.body.style.overflow = "auto";
  }
});

function switchModal(closeId, openId) {
  closeModal(closeId);
  openModal(openId);
}

function setAmount(val) {
  const input = document.getElementById("donationAmount");
  if (input) {
    input.value = val;
  }
}

function openDonateModal(campaignId, title) {
  openModal("donateModal");
  const titleEl = document.getElementById("donateCampaignTitle");
  const input = document.getElementById("donationAmount");
  const idEl = document.getElementById("donateCampaignId");
  const emailEl = document.getElementById("donateEmail");
  if (idEl) {
    idEl.value = campaignId != null ? String(campaignId) : "";
  }
  if (titleEl) {
    titleEl.textContent = title;
  }
  if (input) {
    input.value = "";
  }
  if (emailEl) {
    emailEl.value = cachedUserEmail || "";
  }
}

async function submitDonation() {
  const idEl = document.getElementById("donateCampaignId");
  const emailEl = document.getElementById("donateEmail");
  const amtEl = document.getElementById("donationAmount");
  const cid = idEl && idEl.value ? parseInt(idEl.value, 10) : NaN;
  const email = emailEl ? emailEl.value.trim().toLowerCase() : "";
  const amount = amtEl ? parseFloat(amtEl.value) : NaN;
  if (!cid || Number.isNaN(cid)) {
    showToast("Missing campaign.", true);
    return;
  }
  if (!email) {
    showToast("Enter your email for the receipt.", true);
    return;
  }
  if (!amount || amount < 1 || Number.isNaN(amount)) {
    showToast("Enter an amount of at least Ghc 1.", true);
    return;
  }
  const { res, data } = await apiJson("/api/paystack/initialize", {
    method: "POST",
    body: JSON.stringify({
      campaign_id: cid,
      amount,
      email,
    }),
  });
  if (!res.ok) {
    showToast(data.message || "Could not start payment.", true);
    return;
  }
  if (data.authorization_url) {
    window.location.href = data.authorization_url;
    return;
  }
  showToast("No checkout URL returned.", true);
}

function reportCampaign(title) {
  const el = document.getElementById("reportCampaignTitle");
  if (el) {
    el.innerText = title;
  }
  openModal("reportModal");
}

function toggleProfileMenu() {
  const d = document.getElementById("profileDropdown");
  if (d) {
    d.classList.toggle("show");
  }
}

window.addEventListener("click", (e) => {
  if (!e.target.closest(".user-profile")) {
    const d = document.getElementById("profileDropdown");
    if (d) {
      d.classList.remove("show");
    }
  }
});

function openDashboard() {
  window.location.href = "/dashboard";
}

const yearEl = document.getElementById("year");
if (yearEl) {
  yearEl.textContent = new Date().getFullYear();
}

if (window.location.protocol === "file:") {
  showToast(
    "Open this site via the Flask server (http://127.0.0.1:5000), not as a local file — sign-in will not work from file://",
    true,
  );
}

void refreshUser().then(() => readQueryFlags());
