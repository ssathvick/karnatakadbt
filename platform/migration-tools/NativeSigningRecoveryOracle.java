import java.nio.charset.StandardCharsets;
import java.security.*;
import java.security.cert.Certificate;
import java.util.*;

/** Opens a private recovery copy through the retained Java vault adapter. */
public class NativeSigningRecoveryOracle {
    public static void main(String[] args) throws Exception {
        Class<?> type = Class.forName("org.karnatakadbt.crypto.NativeEncryptedKeyStore");
        Object vault = type.getConstructor(Map.class).newInstance(Map.of("directory", args[0], "scope", "esignet"));
        List<?> aliases = (List<?>) type.getMethod("getAllAlias").invoke(vault);
        int signing = 0;
        for (Object value : aliases) {
            String alias = (String) value;
            PrivateKey key;
            try {
                key = (PrivateKey) type.getMethod("getPrivateKey", String.class).invoke(vault, alias);
            } catch (java.lang.reflect.InvocationTargetException publicOnly) {
                continue;
            }
            Certificate certificate = (Certificate) type.getMethod("getCertificate", String.class).invoke(vault, alias);
            String algorithm = key.getAlgorithm().equals("RSA") ? "SHA256withRSA" :
                    key.getAlgorithm().equals("EC") ? "SHA256withECDSA" : "Ed25519";
            Signature signature = Signature.getInstance(algorithm);
            signature.initSign(key);
            signature.update("owned-recovery-signature".getBytes(StandardCharsets.UTF_8));
            byte[] signed = signature.sign();
            signature.initVerify(certificate);
            signature.update("owned-recovery-signature".getBytes(StandardCharsets.UTF_8));
            if (!signature.verify(signed)) throw new SecurityException("Recovery signature mismatch");
            signing++;
        }
        if (signing == 0) throw new SecurityException("No signing keys recovered");
        System.out.println("{\"passed\":true,\"aliases\":" + aliases.size() + ",\"signing_keys_verified\":" + signing + "}");
    }
}
