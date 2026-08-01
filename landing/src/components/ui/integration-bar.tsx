"use client";

const companies = [
  { name: "Amazon", logo: "/logos/companies/amazon.svg" },
  { name: "JPMorgan Chase", logo: "/logos/companies/jpmorgan.svg" },
  { name: "Google", logo: "/logos/companies/google.svg" },
  { name: "Microsoft", logo: "/logos/companies/microsoft.svg" },
  { name: "Meta", logo: "/logos/companies/meta.svg" },
  { name: "Citibank", logo: "/logos/companies/citibank.svg" },
  { name: "Wells Fargo", logo: "/logos/companies/wellsfargo.svg" },
  { name: "Accenture", logo: "/logos/companies/accenture.svg" },
  { name: "Oracle", logo: "/logos/companies/oracle.svg" },
  { name: "Cisco", logo: "/logos/companies/cisco.svg" },
  { name: "Reliance Industries", logo: "/logos/companies/reliance.svg" },
  { name: "Adobe", logo: "/logos/companies/adobe.svg" },
  { name: "HCL Tech", logo: "/logos/companies/hcltech.svg" },
  { name: "Morgan Stanley", logo: "/logos/companies/morganstanley.svg" },
  { name: "Adani Group", logo: "/logos/companies/adani.svg" },
  { name: "VMware", logo: "/logos/companies/vmware.svg" },
  { name: "Atlassian", logo: "/logos/companies/atlassian.svg" },
  { name: "Red Hat", logo: "/logos/companies/redhat.svg" },
  { name: "UiPath", logo: "/logos/companies/uipath.svg" },
  { name: "Randstad", logo: "/logos/companies/randstad.svg" },
  { name: "Kelly Services", logo: "/logos/companies/kellyservices.svg" },
  { name: "Juniper Networks", logo: "/logos/companies/juniper.svg" },
  { name: "Commvault", logo: "/logos/companies/commvault.svg" },
  { name: "Omnicell", logo: "/logos/companies/omnicell.svg" },
  { name: "Vertex Legal", logo: "/logos/companies/legalzoom.svg" },
  { name: "Swiggy", logo: "/logos/companies/swiggy.svg" },
  { name: "Paytm", logo: "/logos/companies/paytm.svg" },
  { name: "Nykaa", logo: "/logos/companies/nykaa.svg" },
  { name: "OYO", logo: "/logos/companies/oyo.svg" },
  { name: "Razorpay", logo: "/logos/companies/razorpay.svg" },
  { name: "CRED", logo: "/logos/companies/cred.svg" },
  { name: "Meesho", logo: "/logos/companies/meesho.svg" },
  { name: "Zepto", logo: "/logos/companies/zepto.svg" },
  { name: "DoorDash India", logo: "/logos/companies/doordash.svg" },
  { name: "Delhivery", logo: "/logos/companies/delhivery.svg" },
  { name: "Cars24", logo: "/logos/companies/cars24.svg" },
  { name: "Myntra", logo: "/logos/companies/myntra.svg" },
  { name: "BigBasket", logo: "/logos/companies/bigbasket.svg" },
  { name: "Blinkit", logo: "/logos/companies/blinkit.svg" },
  { name: "MobiKwik", logo: "/logos/companies/mobikwik.svg" },
  { name: "NoBroker", logo: "/logos/companies/nobroker.svg" },
  { name: "Disney+ Hotstar", logo: "/logos/companies/hotstar.svg" },
  { name: "HomeLane", logo: "/logos/companies/homelane.svg" },
  { name: "Toast", logo: "/logos/companies/toast.svg" },
  { name: "HackerRank", logo: "/logos/companies/hackerrank.svg" },
  { name: "HackerEarth", logo: "/logos/companies/hackerearth.svg" },
  { name: "Rippling", logo: "/logos/companies/rippling.svg" },
  { name: "Bloomreach", logo: "/logos/companies/bloomreach.svg" },
  { name: "AlphaSense", logo: "/logos/companies/alphasense.svg" },
  { name: "LivePerson", logo: "/logos/companies/liveperson.svg" },
  { name: "BlueJeans", logo: "/logos/companies/bluejeans.svg" },
  { name: "Scaler", logo: "/logos/companies/scaler.svg" },
  { name: "Bright Money", logo: "/logos/companies/brightmoney.svg" },
  { name: "Collegedunia", logo: "/logos/companies/collegedunia.svg" },
  { name: "Hevo", logo: "/logos/companies/hevo.svg" },
  { name: "BarRaiser", logo: "/logos/companies/barraiser.svg" },
  { name: "Findem", logo: "/logos/companies/findem.svg" },
  { name: "Mercor", logo: "/logos/companies/mercor.svg" },
  { name: "Certa", logo: "/logos/companies/certa.svg" },
  { name: "Siena", logo: "/logos/companies/siena.svg" },
  { name: "Liftspace", logo: "/logos/companies/liftspace.svg" },
  { name: "Rev", logo: "/logos/companies/rev.svg" },
  { name: "Hunting Cube", logo: "/logos/companies/huntingcube.svg" },
  { name: "ARIS", logo: "/logos/companies/aris.svg" },
  { name: "AutoDesk", logo: "/logos/companies/autodesk.svg" },
  { name: "Simpl", logo: "/logos/companies/simpl.svg" },
];

function IntegrationBar() {
  return (
    <section id="integration-bar-section" className="py-14 bg-[var(--lp-bg)]">
      <p
        id="integration-bar-label"
        className="font-display text-lg md:text-xl font-light text-[var(--lp-text-muted)] text-center mb-8"
      >
        Built from 300+ conversations with talent leaders at
      </p>

      <div id="integration-bar-inner" className="relative overflow-hidden">
        <div id="integration-bar-fade-left" className="absolute left-0 top-0 bottom-0 w-20 bg-gradient-to-r from-[var(--lp-bg)] to-transparent z-10" />
        <div id="integration-bar-fade-right" className="absolute right-0 top-0 bottom-0 w-20 bg-gradient-to-l from-[var(--lp-bg)] to-transparent z-10" />

        <div id="integration-bar-row" className="flex items-center animate-marquee">
          {[...companies, ...companies].map((company, index) => (
            <div
              key={`ibar-${index}`}
              id={`ibar-${index}`}
              className="flex-shrink-0 mx-5 opacity-50 hover:opacity-80 transition-opacity duration-300"
            >
              <img
                src={company.logo}
                alt={company.name}
                width={120}
                height={32}
                loading="lazy"
                decoding="async"
                className="h-7 md:h-8 w-auto object-contain"
              />
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

export { IntegrationBar };
