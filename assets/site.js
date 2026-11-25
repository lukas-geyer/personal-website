// Lets content settle in as it is scrolled into view. The pages read fully without this file:
// only what lies below the first screen is held back, and nothing is under reduced motion.
(function () {
  if (!('IntersectionObserver' in window) || matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  var observer = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (!entry.isIntersecting) return;
      entry.target.classList.remove('pre');
      observer.unobserve(entry.target);
    });
  }, { rootMargin: '0px 0px -8% 0px' });

  document.querySelectorAll('[data-reveal]').forEach(function (el) {
    if (el.getBoundingClientRect().top < window.innerHeight * 0.92) return;
    el.classList.add('pre');
    observer.observe(el);
  });
})();
