import java.io.*;
import java.nio.file.*;
import java.security.*;
import java.security.cert.*;
import java.util.*;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.danubetech.keyformats.crypto.ByteVerifier;
import foundation.identity.jsonld.JsonLDObject;
import com.apicatalog.jsonld.document.JsonDocument;
import info.weboftrust.ldsignatures.verifier.LdVerifier;
import org.bouncycastle.jce.provider.BouncyCastleProvider;

/** Offline retained-suite verifier using only public certificates. */
public class CredentialSuiteOracle {
    static class PublicVerifier extends ByteVerifier {
        PublicKey key;
        String signatureAlgorithm;
        PublicVerifier(String algorithm, PublicKey publicKey) {
            super(algorithm); key = publicKey;
            signatureAlgorithm = algorithm.equals("RS256") ? "SHA256withRSA" :
                algorithm.equals("EdDSA") ? "Ed25519" : "SHA256withPLAIN-ECDSA";
        }
        protected boolean verify(byte[] data, byte[] signature) throws GeneralSecurityException {
            Signature verifier = Signature.getInstance(signatureAlgorithm, "BC");
            verifier.initVerify(key); verifier.update(data); return verifier.verify(signature);
        }
    }
    @SuppressWarnings("unchecked")
    public static void main(String[] args) throws Exception {
        Security.addProvider(new BouncyCastleProvider());
        ObjectMapper mapper = new ObjectMapper();
        Map<String,Object> catalog = mapper.readValue(Files.readString(Path.of(args[2])), Map.class);
        X509Certificate certificate = (X509Certificate) CertificateFactory.getInstance("X.509", "BC")
            .generateCertificate(Files.newInputStream(Path.of(args[1])));
        JsonLDObject document = JsonLDObject.fromJson(Files.readString(Path.of(args[0])));
        document.setDocumentLoader((uri, options) -> {
            Object value = catalog.get(uri.toString());
            if (value == null) throw new RuntimeException("Unpinned context");
            try { return JsonDocument.of(new StringReader(mapper.writeValueAsString(value))); }
            catch (Exception error) { throw new RuntimeException(error); }
        });
        String suite = ((Map<String,Object>) document.getJsonObject().get("proof")).get("type").toString();
        if (suite.equals("EcdsaSecp256r1Signature2019") || suite.equals("DataIntegrityProof")) {
            // This suite belongs to the retained generic data-integrity library.
            Class<?> type = Class.forName("com.danubetech.dataintegrity.verifier." + suite + "LdVerifier");
            Object verifier = type.getConstructor(ByteVerifier.class).newInstance(new PublicVerifier(args[3], certificate.getPublicKey()));
            Class<?> base = Class.forName("com.danubetech.dataintegrity.verifier.LdVerifier");
            System.out.println("VALID=" + base.getMethod("verify", JsonLDObject.class).invoke(verifier, document));
            ((Map<String,Object>) document.getJsonObject().get("credentialSubject")).put("name", "tampered-synthetic-name");
            System.out.println("TAMPERED=" + base.getMethod("verify", JsonLDObject.class).invoke(verifier, document));
            return;
        }
        Class<?> type = Class.forName("info.weboftrust.ldsignatures.verifier." + suite + "LdVerifier");
        LdVerifier<?> verifier = (LdVerifier<?>) type.getConstructor(ByteVerifier.class)
            .newInstance(new PublicVerifier(args[3], certificate.getPublicKey()));
        System.out.println("REFERENCE_DATA=" + Base64.getEncoder().encodeToString(verifier.getCanonicalizer().canonicalize(
            info.weboftrust.ldsignatures.LdProof.getFromJsonLDObject(document), document)));
        System.out.println("VALID=" + verifier.verify(document));
        ((Map<String,Object>) document.getJsonObject().get("credentialSubject")).put("name", "tampered-synthetic-name");
        System.out.println("TAMPERED=" + verifier.verify(document));
    }
}
