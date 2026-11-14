/* ipe-privacy-age.js · ipe_web_kit.privacy — 생성 파일(python3 -m ipe_web_kit.privacy js). 손으로 고치지 않는다. */
(function (root) {
  'use strict';
  var AGES = {"AE":14,"AR":17,"AT":15,"AU":17,"BE":14,"BG":15,"BR":18,"CA":14,"CA-QC":15,"CH":18,"CL":15,"CN":15,"CO":19,"CY":15,"CZ":16,"DE":17,"DK":16,"EE":14,"EG":18,"ES":15,"FI":14,"FR":16,"GB":14,"GR":16,"HK":18,"HR":17,"HU":17,"ID":19,"IE":17,"IN":19,"IS":14,"IT":15,"JP":17,"KR":15,"LI":17,"LT":15,"LU":17,"LV":14,"MA":18,"MT":14,"MX":19,"MY":19,"NL":17,"NO":16,"NZ":18,"PE":15,"PH":18,"PL":17,"PT":14,"RO":17,"RU":18,"SA":19,"SE":14,"SG":14,"SI":16,"SK":17,"TH":21,"TW":19,"US":14,"UY":18,"VN":17};
  var BLOCKED = ["CN", "RU"];
  var DEFAULT_AGE = 18;
  var tag = typeof document !== 'undefined' && document.currentScript;
  var siteDefault = tag && parseInt(tag.getAttribute('data-default-age'), 10);
  function code(cc) { return String(cc || '').trim().toUpperCase().replace('_', '-'); }
  function minAge(cc, opts) {
    var c = code(cc), base = c.split('-')[0];
    if (Object.prototype.hasOwnProperty.call(AGES, c)) return AGES[c];
    if (Object.prototype.hasOwnProperty.call(AGES, base)) return AGES[base];
    var d = opts && opts.defaultAge;
    return d > 0 ? d : (siteDefault > 0 ? siteDefault : DEFAULT_AGE);
  }
  function commentsAllowed(cc) { return BLOCKED.indexOf(code(cc).split('-')[0]) < 0; }
  function canComment(cc, year, month, opts) {
    if (!commentsAllowed(cc)) return false;
    var now = (opts && opts.now) || new Date();
    var age = now.getFullYear() - year - ((now.getMonth() + 1) <= month ? 1 : 0);
    return age >= minAge(cc, opts);
  }
  var api = { minAge: minAge, commentsAllowed: commentsAllowed, canComment: canComment, AGES: AGES, DEFAULT_AGE: DEFAULT_AGE };
  if (typeof module === 'object' && module.exports) module.exports = api; else root.IpePrivacy = api;
})(typeof self !== 'undefined' ? self : this);
