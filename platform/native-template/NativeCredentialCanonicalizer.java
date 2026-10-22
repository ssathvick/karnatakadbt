import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import com.fasterxml.jackson.databind.ObjectMapper;
import foundation.identity.jsonld.JsonLDObject;
import com.apicatalog.jsonld.document.JsonDocument;

/** Bounded data-only adapter to generic RDFC/JCS libraries; no business code or keys. */
public final class NativeCredentialCanonicalizer {
    @SuppressWarnings("unchecked")
    public static void main(String[] args) throws Exception {
        if (args.length != 1) throw new IllegalArgumentException();
        byte[] input = System.in.readNBytes(1048577);
        if (input.length > 1048576) throw new IllegalArgumentException();
        ObjectMapper mapper = new ObjectMapper();
        Map<String,Object> request = mapper.readValue(input, Map.class);
        String suite = (String) request.get("suite");
        String canonicalizer = switch (suite) {
            case "eddsa-rdfc-2022", "ecdsa-rdfc-2019" -> "RDFC10SHA256Canonicalizer";
            case "eddsa-jcs-2022", "ecdsa-jcs-2019" -> "JCSSHA256Canonicalizer";
            default -> throw new IllegalArgumentException();
        };
        Map<String,Object> catalog = mapper.readValue(Files.readString(Path.of(args[0])), Map.class);
        JsonLDObject document = JsonLDObject.fromJson(mapper.writeValueAsString(request.get("document")));
        document.setDocumentLoader((uri, options) -> {
            Object value = catalog.get(uri.toString());
            if (value == null) throw new RuntimeException("Unpinned context");
            try { return JsonDocument.of(new StringReader(mapper.writeValueAsString(value))); }
            catch (Exception error) { throw new RuntimeException(error); }
        });
        Class<?> proofType = Class.forName("com.danubetech.dataintegrity.DataIntegrityProof");
        Object proof = proofType.getMethod("fromJsonObject", Map.class).invoke(null, request.get("proof"));
        Class<?> type = Class.forName("com.danubetech.dataintegrity.canonicalizer." + canonicalizer);
        Object normalizer = type.getMethod("getInstance").invoke(null);
        byte[] result = (byte[]) type.getMethod("canonicalize", proofType, JsonLDObject.class).invoke(normalizer, proof, document);
        if (result.length != 64) throw new IllegalStateException();
        System.out.write(Base64.getEncoder().encode(result));
    }
}
