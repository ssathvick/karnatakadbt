# Third-party notices and provenance

KarnatakaDBT is a custom application framework built using open-source software. It is not an Odoo/ERPNext installation. The local Compose topology does not deploy OpenG2P or MOSIP business binaries.

The repository retains historical API contracts, migration utilities, schema/role names and compatibility references from earlier OpenG2P/MOSIP interfaces. These references do not imply endorsement or an active runtime dependency. Respect all original notices and applicable licences for adapted material. OpenG2P Registry Platform and MOSIP eSignet publish MPL-2.0 material; individual projects/components may carry different licences. Public availability of this repository does not relicense third-party works.

* [OpenG2P licensing guidance](https://github.com/OpenG2P/openg2p-documentation/blob/latest/license.md)
* [OpenG2P Registry Platform](https://github.com/OpenG2P/registry-platform)
* [MOSIP eSignet](https://github.com/mosip/esignet)
* [Mozilla Public License 2.0](https://www.mozilla.org/en-US/MPL/2.0/)

The retained [source provenance manifest](SOURCE-PROVENANCE.json) records reused project assets. It is not a complete copyright audit.

Infrastructure is distributed by its respective publishers: PostgreSQL (PostgreSQL licence), Redis (licence depends on selected release), Keycloak (Apache-2.0), Apache Kafka (Apache-2.0), Caddy (Apache-2.0), and MinIO community server (AGPL-3.0). MinIO is built from its pinned public source tag; its applicable source is available at https://github.com/minio/minio/tree/RELEASE.2025-10-15T17-29-55Z. Docker's and infrastructure vendors' licences/terms apply independently.

Python/JavaScript dependencies retain their package licences. Generic Java rendering/canonicalization libraries are listed with hashes and Maven coordinates in `vendor/java/manifest.json`; extracted licence/notice files are retained in `vendor/licenses/`. No MOSIP/OpenG2P business-class JARs are included in that library set.

Project-authored source and deployment additions are released under the Mozilla Public License 2.0 (see LICENSE), subject to the separate licences/notices of third-party material. Retain applicable notices when modifying or distributing files.
